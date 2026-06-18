# HK Calibration Portrait - felhasznaloi guide annotacios kepgyujteshez

Ez a rovid guide azt irja le, hogyan lehet a Jetsonon elinditani a bongeszos
feluletet, ellenorizni a `hk_calibration_app_portrait` mukodeset, majd
annotaciohoz kepeket gyujteni.

## 1. QT app lezarasa a Jetsonon

Ha a Jetsonon meg fut a teljes kepernyos QT alkalmazas, zard be:

```text
ALT + F4
```

Ezutan a desktopon megnyithato a bongeszos frontend.

## 2. Chromium megnyitasa

1. A Jetson bal oldali alkalmazas-savjaban nyisd meg a Chromium bongeszot.
2. Ird be a cimsorba:

```text
http://localhost:8080
```

Ez az alkalmazasvalaszto oldal. Innen valaszthato ki a kalibracios, kezelesi,
kamera-teszt es annotacios felulet.

## 3. Calibration Portrait app hasznalata

Az alkalmazasvalasztoban valaszd:

```text
Calibration Portrait
```

Ez nyitja meg a `hk_calibration_app_portrait.html` feluletet.

A kalibracios app celja, hogy a kamera kepkoordinatait osszekosse a galvo
pozicioival. Ez kell ahhoz, hogy a rendszer tudja: a kamera kepen kijelolt pont
melyik galvo pozicionak felel meg.

Fobb panelek:

- `Camera Stream`: elo kamerakep.
- `Red Dot Detection (Calibration)`: piros pont detektalas be/ki, maszk overlay,
  HSV kattintasos ellenorzes.
- `HSV Limits`: a piros pont felismeresi tartomanyainak finomhangolasa.
- `Laser Control`: ARM/DISARM es piros pont ki/be kapcsolasa.
- `Direct Galvo Control`: galvo kezi mozgatasa X/Y koordinataval vagy nyilakkal.
- `Calibration Collection`: kalibracios pontok gyujtese es homografia mentese.
- `Homography Test`: kepre kattintva ellenorizheto, hogy a mentett homografia
  jo galvo pozicioba mozgat-e.

Alap kalibracios folyamat:

1. Kapcsold be az `Enable red dot detection overlay` opciot.
2. Kapcsold be a piros pontot a `Red Dot ON` gombbal.
3. Ha a piros pont nem stabilan latszik, hasznald a `Show mask overlay` es
   `HSV inspect click mode` opciokat, majd allitsd a HSV csuszkakat.
4. A `Direct Galvo Control` panelen mozgasd a pontot kulonbozo helyekre.
5. Minden jo, lathato pozicional nyomd meg a `Store Point` gombot.
6. Legalabb 4 pont kell, de erdemes tobb pontot gyujteni a kep kulonbozo
   reszein.
7. Nyomd meg a `Calculate & Save Homography` gombot.
8. A `Homography Test` reszben kattints a kamerakepre, es ellenorizd, hogy a
   galvo oda mozog-e, ahova varod.

## 4. Kepek gyujtese annotaciohoz

Fontos: a `Calibration Portrait` app kalibral, de nem ez menti az annotacios
dataset kepeit. Annotacios kepek gyujtesehez lepj vissza az alkalmazasvalasztoba:

```text
http://localhost:8080
```

Valaszd:

```text
Annotation Capture
```

A `hk_annotation_capture.html` feluleten:

1. Ellenorizd a `Backend API base` mezot. Jetsonon altalaban:

   ```text
   http://localhost:8000/api
   ```

2. A `Store directory` mezobe ird be a cel mappat, peldaul:

   ```text
   annotation_images
   ```

3. Toltsd ki a `Creator` mezot nevvel vagy monogrammal.
4. A `Description` mezobe ird be, milyen korulmenyek kozott keszul a kep
   (peldaul feny, pozicio, bor/szur tipus, fokusz).
5. A kamerakepen ellenorizd, hogy a kep eles es a celterulet lathato.
6. Nyomd meg a `Save Raw + Cropped` gombot.
7. A `Last Capture` panelen ellenorizd, hogy a mentes sikeres volt.

Javaslat annotacios adatgyujteshez:

- Gyujts valtozatos kepeket: tobb pozicio, fokusz, megvilagitas es tavolsag.
- Ne csak idealis kepeket ments; hasznosak a nehezebb esetek is.
- Rossz, bemozdult vagy rosszul megvilagitott kepnel inkabb keszits uj mintat.
- A `Description` mezobe irt rovid megjegyzes kesobb sokat segit az annotalasnal.

## 5. Gyors hibakereses

- Ha nincs kamerakep: frissitsd az oldalt, vagy ellenorizd, hogy fut-e a backend.
- Ha a piros pont nem latszik: kapcsold be a `Red Dot ON` gombot es ellenorizd
  az ARM/piros pont allapotot.
- Ha a piros pont overlay rosszul talal: hasznald a HSV inspect modot es allitsd
  a HSV limiteket.
- Ha az annotacios mentes hibazik: ellenorizd, hogy a `Creator` es
  `Store directory` mezok ki vannak-e toltve.
