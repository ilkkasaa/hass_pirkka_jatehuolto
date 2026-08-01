# Home Assistant -integraatio: Pirkanmaan Jätehuollon seuraavat tyhjennyspäivät

Tämä projekti sisältää Home Assistant custom_component -integraation, joka hakee Pirkanmaan Jätehuollon Oma jätehuolto -palvelusta astioiden seuraavat tyhjennyspäivät.

## Ominaisuudet
- Yksi sensori per astia (seuraava tyhjennyspäivä)
- Diagnostiikkasensori `Error` integraation tilalle
- Diagnostiikkasensori `Last updated` viimeisimmälle onnistuneelle päivitykselle
- VUOKRA-rivit suodatetaan pois (vuokratut jäteastiat)
- Dynaaminen päivitystahti, joka minimoi turhat HTTP-pyynnöt
- Tekoälyn tuottama
- Käyttö omalla vastuulla

## Asennus:
1. Kopioi tiedostot kansioon:
`custom_components/pirkka_jatehuolto`
2. Käynnistä Home Assistant uudelleen.
3. Lisää integraatio

## Lisenssi
Tämä projekti on lisensoitu MIT-lisenssillä. Katso [license.md](license.md).

## Vastuuvapauslauseke
Minulla ei ole mitään yhteyttä Pirkanmaan Jätehuolto Oy:hyn. Tämä on epävirallinen, yhteisön tekemä projekti.
