# Paraksta atslēga

`ci.p12` ir **apzināti nenoslēpumaina** atslēga (parole `estudijas-ci`), ar ko GitHub Actions paraksta APK,
lai katra jaunā versija instalētos virsū iepriekšējai (Android prasa vienu un to pašu parakstu).

Ja gribi savu, slepenu atslēgu: repozitorija **Settings → Secrets and variables → Actions** pievieno
`ANDROID_KEYSTORE_B64` (keystore faila base64) un `ANDROID_KEYSTORE_PASSWORD`. Tad būvēšana izmantos to.
Uzmanību: pēc atslēgas maiņas vecā lietotne telefonā vienreiz jāizdzēš un jāinstalē no jauna.
