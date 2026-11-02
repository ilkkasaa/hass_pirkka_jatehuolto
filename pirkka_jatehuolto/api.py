"""API client for Pirkanmaan Jätehuolto."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import logging
from typing import Any

from aiohttp import ClientError, ClientSession
from yarl import URL

from .const import BASE_URL

_LOGGER = logging.getLogger(__name__)


class PirkkaApiError(Exception):
    """Base class for API errors."""


class PirkkaInvalidAuth(PirkkaApiError):
    """Raised when credentials are invalid."""


class PirkkaCannotConnect(PirkkaApiError):
    """Raised when connection to service fails."""


class PirkkaDataError(PirkkaApiError):
    """Raised when service data cannot be parsed."""


class PirkkaUnsupportedFlow(PirkkaApiError):
    """Raised when login flow requires browser-only actions."""


@dataclass(slots=True)
class BinEmptying:
    """Single bin emptying info."""

    bin_id: str
    name: str
    next_emptying: date | None


class PirkkaApiClient:
    """Client for the Pirkanmaan Jätehuolto extranet."""

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
        base_url: str = BASE_URL,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._is_logged_in = False

    async def fetch_bins(self) -> list[BinEmptying]:
        """Log in and fetch bin emptying dates."""
        # Refreshes are hours or days apart, so the previous server session has
        # most likely expired. The service answers stale sessions with HTTP 500
        # instead of 401, so always start from a fresh login.
        self._reset_session()
        await self._login()

        customer_data = await self._get_json("/secure/get_customer_datas.do")
        customer_groups = self._extract_customer_groups(customer_data)
        customer_numbers = sorted({n for group in customer_groups for n in group})

        if not customer_numbers:
            return []

        services: list[dict[str, Any]] = []
        for group_numbers in customer_groups:
            if not group_numbers:
                continue
            group_services = await self._get_services_for_customer_numbers(group_numbers)
            services.extend(group_services)

        bins: list[BinEmptying] = []
        for service in services:
            if not isinstance(service, dict):
                continue

            tariff = service.get("tariff") if isinstance(service.get("tariff"), dict) else {}
            service_id = service.get("id") if isinstance(service.get("id"), dict) else {}

            name = str(tariff.get("name") or service_id.get("ASTTyyppi") or "Tuntematon astia")

            if "vuokra" in name.lower():
                # Rented bin entries are not actual emptying schedule sensors.
                continue

            if "ASTNextDate" not in service:
                # Non-bin services do not expose next emptying details.
                continue

            customer_number = str(service_id.get("ASTAsnro") or "")
            astkal = str(service.get("ASTKALTunnus") or "")
            fallback_id = str(service_id.get("ASTTyyppi") or name).replace(" ", "_").lower()
            bin_id = "_".join(part for part in [customer_number, astkal, fallback_id] if part)

            next_emptying = self._parse_date(service.get("ASTNextDate"))
            bins.append(BinEmptying(bin_id=bin_id, name=name, next_emptying=next_emptying))

        return bins

    def _reset_session(self) -> None:
        """Forget login state and drop stale session cookies for the service."""
        self._is_logged_in = False
        host = URL(self._base_url).host
        if host:
            self._session.cookie_jar.clear_domain(host)

    async def _login(self) -> None:
        """Authenticate and establish session cookies."""
        if self._is_logged_in:
            return

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{self._base_url}/sahas.jsp",
        }

        # Prime session cookies and locale similarly to a browser login flow.
        try:
            async with self._session.get(f"{self._base_url}/sahas.jsp", headers=headers):
                pass
        except ClientError as err:
            _LOGGER.warning("Esipyyntö sahas.jsp epäonnistui: %s", err)
            raise PirkkaCannotConnect("Cannot connect to service") from err

        login_url = f"{self._base_url}/j_acegi_security_check?target=2"
        payload = {
            "j_username": self._username,
            "j_password": self._password,
            "remember-me": False,
        }

        try:
            async with self._session.post(login_url, data=payload, headers=headers) as response:
                content_type = (response.headers.get("content-type") or "").lower()

                if response.status in (401, 403):
                    _LOGGER.warning("Kirjautuminen hylättiin HTTP-statuksella %s", response.status)
                    raise PirkkaInvalidAuth("Invalid username or password")

                if response.status >= 500:
                    _LOGGER.warning("Palvelinvirhe kirjautumisessa HTTP-statuksella %s", response.status)
                    raise PirkkaCannotConnect("Server error during login")

                if "application/json" in content_type:
                    data = await self._read_json_response(response, path="/j_acegi_security_check")
                    if not isinstance(data, dict):
                        raise PirkkaDataError("Unexpected login response format")
                    if data.get("response") == "OK":
                        self._is_logged_in = True
                        return

                    _LOGGER.warning("Kirjautumisen JSON-vastaus ei ollut OK: %s", data)
                    raise PirkkaInvalidAuth("Login rejected")

                # HTML responses indicate additional browser-only login steps
                # (password change, terms acceptance, etc.) or failed auth flow.
                if "text/html" in content_type:
                    x_url = response.headers.get("X-Url", "")
                    _LOGGER.debug(
                        "Login returned HTML: status=%s x_url=%s",
                        response.status,
                        x_url,
                    )
                    if x_url == "pw.do":
                        raise PirkkaUnsupportedFlow(
                            "Tili vaatii salasanan vaihdon selaimessa ennen integraatiota"
                        )

                    raise PirkkaUnsupportedFlow(
                        "Tili vaatii lisävaiheita selaimessa (esim. ehdot), joita integraatio ei voi suorittaa"
                    )

                raise PirkkaDataError(f"Unsupported login response type: {content_type}")

        except ClientError as err:
            _LOGGER.warning("Kirjautumispyyntö epäonnistui: %s", err)
            raise PirkkaCannotConnect("Cannot connect to service") from err

    async def _get_json(self, path: str, params: list[tuple[str, str]] | None = None) -> Any:
        """Perform a JSON GET request with automatic re-login if session expired."""
        url = f"{self._base_url}{path}"
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{self._base_url}/sahas.jsp",
        }

        try:
            async with self._session.get(url, params=params, headers=headers) as response:
                content_type = (response.headers.get("content-type") or "").lower()

                if response.status in (401, 403):
                    self._is_logged_in = False
                    _LOGGER.warning("Sessio hylättiin pyynnössä %s HTTP-statuksella %s", path, response.status)
                    raise PirkkaInvalidAuth("Session unauthorized")

                if response.status >= 400:
                    _LOGGER.warning("Pyyntö %s epäonnistui HTTP-statuksella %s", path, response.status)
                    raise PirkkaCannotConnect(f"Request failed: {response.status}")

                if "application/json" not in content_type:
                    text = await response.text()
                    _LOGGER.debug(
                        "Non-JSON response from %s: status=%s content_type=%s snippet=%s",
                        path,
                        response.status,
                        content_type,
                        text[:200],
                    )
                    if "kirjaudu" in text.lower() or "login" in text.lower():
                        self._is_logged_in = False
                        raise PirkkaInvalidAuth("Session expired")
                    raise PirkkaDataError(f"Expected JSON but got: {content_type}")

                return await self._read_json_response(response, path=path)

        except PirkkaInvalidAuth:
            # Session might have expired; retry once after re-login.
            _LOGGER.debug("Session expired, attempting one re-login")
            self._is_logged_in = False
            await self._login()
            try:
                async with self._session.get(url, params=params, headers=headers) as retry_response:
                    if retry_response.status >= 400:
                        raise PirkkaCannotConnect(f"Request failed: {retry_response.status}")
                    return await self._read_json_response(retry_response, path=path)
            except ClientError as err:
                _LOGGER.warning("Uudelleenkirjautumisen jälkeinen pyyntö %s epäonnistui: %s", path, err)
                raise PirkkaCannotConnect("Cannot connect to service") from err
        except ClientError as err:
            _LOGGER.warning("Pyyntö %s epäonnistui: %s", path, err)
            raise PirkkaCannotConnect("Cannot connect to service") from err

    async def _read_json_response(self, response: Any, path: str) -> Any:
        """Decode JSON response and normalize decode/type errors."""
        try:
            text = await response.text()
        except ClientError as err:
            raise PirkkaCannotConnect("Cannot connect to service") from err
        except Exception as err:  # noqa: BLE001
            raise PirkkaDataError("Failed to decode response body") from err

        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            _LOGGER.warning(
                "Virheellinen JSON vastauksessa %s (status=%s): %s",
                path,
                response.status,
                err,
            )
            raise PirkkaDataError("Invalid JSON response from service") from err

    async def _get_services_for_customer_numbers(self, customer_numbers: list[str]) -> list[dict[str, Any]]:
        """Fetch services using backend-compatible array encodings."""
        path = "/secure/get_services_by_customer_numbers.do"

        # jQuery-style serialization used by the website: customerNumbers[]=a&customerNumbers[]=b
        candidates: list[list[tuple[str, str]]] = [
            [("customerNumbers[]", number) for number in customer_numbers],
            [("customerNumbers", number) for number in customer_numbers],
            [("customerNumbers", ",".join(customer_numbers))],
        ]

        last_error: Exception | None = None
        for idx, params in enumerate(candidates, start=1):
            try:
                data = await self._get_json(path, params=params)
                if not isinstance(data, list):
                    raise PirkkaDataError("Unexpected service response format")
                return data
            except PirkkaCannotConnect as err:
                if "Request failed: 400" not in str(err):
                    raise
                last_error = err
                _LOGGER.warning(
                    "Palvelulistan parametri-muoto #%s aiheutti HTTP 400, kokeillaan vaihtoehtoista muotoa",
                    idx,
                )

        if last_error is not None:
            raise last_error
        raise PirkkaDataError("Service request failed")

    @staticmethod
    def _extract_customer_groups(data: Any) -> list[list[str]]:
        """Extract customer number groups from get_customer_datas response."""
        groups_out: list[list[str]] = []

        if isinstance(data, dict):
            groups = data.values()
        elif isinstance(data, list):
            groups = data
        else:
            raise PirkkaDataError("Unexpected customer data structure")

        for group in groups:
            if not isinstance(group, list):
                continue
            group_numbers: list[str] = []
            for customer in group:
                if not isinstance(customer, dict):
                    continue
                number = customer.get("asiakasnro")
                if number is None:
                    continue
                group_numbers.append(str(number))
            if group_numbers:
                groups_out.append(sorted(set(group_numbers)))

        return groups_out

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        """Parse date from known API formats."""
        if value in (None, ""):
            return None

        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value).date()
            except (OSError, OverflowError, ValueError):
                return None

        raw = str(value).strip()
        candidates = [
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%d.%m.%Y",
        ]

        for fmt in candidates:
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue

        # ISO values with timezone suffix, e.g. 2026-08-01T00:00:00+03:00
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None
