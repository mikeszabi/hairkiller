*********************************************************
Readme doksi Mike Szabolcsnak tesztelésre.
branch: szabi-teszt
tag: V1.0
2026.02.11.
Author: Csőke Lóránt Optimal Optik Kft.
*********************************************************

---------- Kommunikáció fizikai layer -------------
USB Virtual COM port
Baud: 115200
Parity: None
Stop bits: 1
Data bits: 8

---------- Galvo pozíciók -------------
GALVO pozíciók szemre
CENTER (X,Y) 2900, 2900 // Ez a default érték indulás után
TOP (X,Y) 2900,1200
LEFT (X,Y) 1250,2900
RIGHT (X,Y) 4095,2900 1 centi hiányzik...
BOTTOM (X,Y) 2900,2900 szintén 1 centi hiányzik

Tartomány illusztráció
 ------------------> (X)
|               |
|Galvo tartomány|
|            ---|
|          /    |\
|         | Szőr| |
|__________\____|/
V (Y)        ---


---------- Basic parancsok -------------
Ismeretlen parancs.
	válasz: ERR: Unknown CMD

Státusz info
STATUS
	válasz jó esetben: STATUS: T: 30629mC RH: 21792mRH P: 981mBar Fiber: 1
	válasz hiba esetén:	STATUS: ERR: "Valami hibaüzenet"

Életjel
PING
	válasz: PING: OK
	
Reset
RESET
	válasz: RESET: OK
	
Lézer direkt teljesítményállítás. !!!Veszélyes, csak teszt kódban lesz benn.!!!
Állítja az adott lézer meghajtóáramát %-ban 1-100% között.
0 - 660
1 - 808
2 - 980
3 - 1064
4 - ALL
SET_LASER_PWR 1-4,1-100 
	válasz jó esetben: SET_LASER_PWR: OK
	válasz hiba esetén: SET_LASER_PWR: ERR: "Valami hibaüzenet"

Lézer táp (3.3V 50A) bekapcsolása/kikapcsolása. !!!Veszélyes, csak teszt kódban lesz benn.!!!
Alapvetően ezt a ARM_LASER command csinálja majd, ez is teszt jelleggel van bent.
SET_LASER_DCDC 1/0
	válasz jó esetben: SET_LASER_DCDC: OK
	válasz hiba esetén: SET_LASER_DCDC: ERR: "Valami hibaüzenet"
	válasz jó esetben:
	válasz hiba esetén:
	
Áramszabályozó engedélyezése/tiltása. !!!Veszélyes, csak teszt kódban lesz benn.!!!
Innentől a szabályozó az alapjelre szabályoz amit a SET_LASER_PWR-rel beállítottunk.
0 - 660
1 - 808
2 - 980
3 - 1064
4 - ALL
SET_LASER_STATE 1-4, 1/0
	válasz jó esetben: SET_LASER_STATE: OK

Lézer biztonsági rövidzárak megszüntetése. "Utolsó safety mechanizmus" !!!Veszélyes, csak teszt kódban lesz benn.!!!
0: Lézer rövidzár ki, lézer hajtható és világít
1: Lézer rövidzár be, az áram a rövidrezáró FET-en folyik ha mégis meghajtódna.
Ideális esetben ezt csak akkor kapcsoljuk be, ha már a SET_LASER_STATE 0-ba van állítva.
SET_SHUNT_STATE 1/0
	válasz jó esetben: SET_SHUNT_STATE: OK
	válasz hiba esetén: SET_SHUNT_STATE: ERR: "Valami hibaüzenet"

Galvo kézi pozícióra állítása.
SET_GALVO_POS_XY 0-4095,0-4095
	válasz jó esetben: SET_GALVO_POS_XY: OK
	válasz hiba esetén: SET_GALVO_POS_XY: ERR: "Valami hibaüzenet"

Galvo pozíció visszacsolójelének olvasása.
Ez nem kell megegyezzen a kiküldött pozíciójellel, csak valamilyen formában aránylik ahhoz.
Tehát SET_GALVO_POS_XY 1000,1000 után nem kell a GET_GALVO_POS_XY-nak X:1000, Y1000-et visszaadnia.
Tesztelt eredmény: X:2733, Y:964 SET_GALVO_POS_XY 1000,1000 esetén
GET_GALVO_POS_XY
	válasz jó esetben: GET_GALVO_POS_XY: X:2243, Y:922
	válasz hiba esetén: GET_GALVO_POS_XY: ERR: "Valami hibaüzenet"

Lézer meghajtó elektronika indítása. Megnézi a következő paramétereket hogy stimmelnek-e és csak akkor engedi:
Nem aktív a lézer
Van szál a lézerbe bedugva
A lézer belső hőmérséklete 20-25 °C között van.
A vezérlő elektronika hőmérséklete 20-50 °C között van-e.
A vezérlő elektronika környezeti páratartalma 50%RH-nál kevesebb.
ARM_LASER
	válasz jó esetben: ARM_LASER: OK
	válasz hiba esetén: ARM_LASER: "Valami hibaüzenet" pl: ERR: Laser temperature out of operating conditions. T: 0mC.

Lézer hatástalanítása. Kikapcsolj a lézer tápot, shuntoli a lézereket, letiltja a szabályozót.
DISARM_LASER
	válasz jó esetben: DISARM_LASER: OK
	Mást nem adhat, ez safety miatt bármikor le kell fusson
	
Hibaüzenet nyugtázása.
Egyes hibák esetén error állapotba kerül az eszköz, letiltja a legtöbb funkcióját.
Ezzel a paranccsal lehet nyugtázni. 
Még sok implementáció hiányzik, bizonyára lesznek nem nyugtázható fatális hibák, és lehetnek kevésbé súlyosak.
ACK_ERRORS
	válasz jó esetben: ACK_ERRORS: OK
	válasz hiba esetén: ACK_ERRORS: ERR: "Valami hibaüzenet"

---------- Szekvencia megadás és vezérlés parancsok -------------
Itt azok a parancsok vannak felsorolva, melyek az automata célzás beállítására szolgálnak

Kiválasztja az aktív lézerekt a lövéshez. A boolok sorrendje: 1064, 980, 808, 660
SET_ACTIVE_LASERS 1,1,1,0
	válasz jó esetben: SET_ACTIVE_LASERS: OK
	válasz hiba esetén: SET_ACTIVE_LASERS: ERR: "Valami hibaüzenet"
	
Lézer teljesítmény állítás %-ban [1-100],  az összes kiválaszott lézert ezen a teljesítményen üzemelteti.
SET_LAS_CURR 1-100
	válasz jó esetben: SET_LAS_CURR: OK
	válasz hiba esetén: SET_LAS_CURR: ERR: "Valami hibaüzenet"

Impulzus idő beállítása, ennyi ms-ig lesz a lézer aktív.
SET_LAS_PULSE 1-1000
	válasz jó esetben: SET_LAS_PULSE: OK
	válasz hiba esetén: SET_LAS_PULSE: ERR: "Valami hibaüzenet"

Hány db pontot szeretnék végiglőni, azaz a következő START_SEQ-re ennyi célponton fog végigmenni.
SET_SEQ_LENGTH 1-256
	válasz jó esetben: SET_SEQ_LENGTH: OK
	válasz hiba esetén: SET_SEQ_LENGTH: ERR: "Valami hibaüzenet"

Célpontok hozzáadása.
SET_TARGET_POINT 0-255,0-4095,0-4095 (idx, xPos, yPos)
	válasz jó esetben: SET_TARGET_POINT: OK
	válasz hiba esetén: SET_TARGET_POINT: ERR: "Valami hibaüzenet"
	
Szekvencia indítása élseben. 
(Ez most nem fog menni, megnéz sok paramétert hogy rendben van-e pl vákuum,
lézer driver rész aktív-e, be van-e dugva szál a lézerbe etc...)
START_SEQ
	válasz jó esetben: START_SEQ: OK
	válasz hiba esetén: START_SEQ: ERR: "Valami hibaüzenet"
	válasz sikeres befejezés esetén: INFO: Sequence finished
	
Szekvencia indítása teszt jelleggel. Végigmegy a megadott target pontokon mindenféle check nélkül.
Egyedül azt vizsgálja, hogy a targetCnt (amit a SET_SEQ_LENGTH paranccsal állítasz) nem 0-e.
Fontos, hogy sequence után ez kinullázódik, viszont minden más paraméter és a target koordináták is megmaradnak.
Ha újra akarod lőni ugyanazokat a koordinátákat, akkor csak a targetCnt-ot kell újra beírni.
Befejezés után visszaáll a galvo középre.
START_SEQ_TEST
	válasz jó esetben: START_SEQ_TEST: OK
	válasz hiba esetén: START_SEQ_TEST: ERR: "Valami hibaüzenet"
	válasz sikeres befejezés esetén: INFO: Sequence finished
	
Szekvencia teljes abortálása
Megállítja a sorozatot, kinullázza a targetCnt-ot.
STOP_SEQ
	válasz jó esetben: STOP_SEQ: OK
	válasz hiba esetén: STOP_SEQ: ERR: "Valami hibaüzenet"
	
Szekvencia "pause". Megállítja, de nem abortálja a processzt, az éppen futó lövést még befejezi.
HALT_SEQ
	válasz jó esetben: HALT_SEQ: OK
	válasz hiba esetén: HALT_SEQ: ERR: "Valami hibaüzenet"
	
Folytatja ahonnan abbahagyta.
RESUME_SEQ
	válasz jó esetben: RESUME_SEQ: OK
	válasz hiba esetén: RESUME_SEQ: ERR: "Valami hibaüzenet"

Példa egy rövid sorozatra. Egy horizontális vonal mentén 5 pont.
808, 980, 1064 lézerek fognak lőni
1000 ms hosszan, nyilván teszt miatt ilyen hosszú, hogy lássuk
5 db pontból fog állni a sorozat
pontok megadása 0-4-ig indexelve
sorozat indítása

SET_ACTIVE_LASERS 1,1,1,0
SET_LAS_CURR 50
SET_LAS_PULSE 1000
SET_SEQ_LENGTH 5
SET_TARGET_POINT 0,2000,2900
SET_TARGET_POINT 1,2400,2900
SET_TARGET_POINT 2,2800,2900
SET_TARGET_POINT 3,3200,2900
SET_TARGET_POINT 4,3600,2900
START_SEQ_TEST