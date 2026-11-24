# Ropam Neo dla Home Assistant

Integracja HACS dla central alarmowych **Ropam serii Neo-IP**: NeoLTE-IP, NeoLTE-IP-PS, NeoGSM-IP i Neo-IP (bez „64”). Te modele nie mają MQTT ani Modbusa, więc integracja łączy się z centralą lokalnie tym samym kanałem co aplikacja RopamNeo (TCP, port 9999). Chmura i RopamBridge nie są potrzebne.

> Projekt nieoficjalny, niezwiązany z Ropam Elektronik. Protokół został odtworzony na potrzeby współpracy z własną centralą. Używasz na własną odpowiedzialność.

## Co dostajesz

| Encja | Opis |
|---|---|
| `alarm_control_panel` | Strefa 1 i 2: uzbrój, uzbrój nocne, rozbrój. Stany: rozbrojony, uzbrojony, nocny, czas na wyjście, czas na wejście, alarm |
| `binary_sensor` | Wejścia (czujki). Atrybuty: sabotaż, pamięć alarmu, blokada, awaria, słaba bateria |
| `switch` | Wyjścia, którymi wolno sterować z aplikacji |
| `binary_sensor` | Wyjścia bez prawa sterowania (tylko stan), sabotaż stref, zasilanie 230V, połączenie |
| `sensor` | Temperatury (TSR), wejście analogowe AI, napięcie zasilania, wilgotność, ostatni komunikat z centrali |

Nazwy wejść, wyjść i stref pobierane są z konfiguracji centrali.

Komunikaty z centrali (np. „nie można uzbroić”) trafiają do sensora *Ostatni komunikat* i jako zdarzenie `ropam_neo_message`.

## Instalacja

1. HACS → ⋮ → *Własne repozytoria* → `https://github.com/voltronicpl/ropam-neo-ha`, kategoria **Integracja**.
2. Zainstaluj **Ropam Neo** i zrestartuj HA.
3. *Ustawienia → Urządzenia i usługi → Dodaj integrację → Ropam Neo*.

## Formularz

| Pole | Skąd wziąć |
|---|---|
| Adres IP centrali | IP centrali w sieci lokalnej. Zarezerwuj go w routerze (DHCP) |
| Port | `9999` |
| ID centrali | 16 znaków. NeoGSM-IP Manager albo dane z kodu QR dla aplikacji RopamNeo |
| Klucz TCP/IP | Klucz szyfrowania aplikacji (NeoGSM-IP Manager → komunikacja) |
| Kod użytkownika | Kod użytkownika z uprawnieniem do aplikacji. Służy do logowania oraz do uzbrajania i rozbrajania |

Dane można zmienić później: karta integracji → **Konfiguruj**.

Dane są zapisywane tylko w konfiguracji HA. W logach i diagnostyce są maskowane.

**Zalecenie:** załóż w centrali osobnego użytkownika dla Home Assistant, z dostępem tylko do potrzebnych stref, zamiast używać kodu głównego.

## Ustawienia w centrali (NeoGSM-IP Manager)

- Centrala w sieci WiFi/LAN, z dostępem do aplikacji mobilnej.
- Użytkownik z uprawnieniem do aplikacji i do stref, którymi ma sterować HA.
- Wyjścia, które mają być switchami, muszą mieć zaznaczoną opcję **„Aplikacja mobilna”**. Pozostałe pojawią się tylko jako stan.

## Zakładka diagnostyki

W menu bocznym pojawia się **Ropam Neo** (tylko dla admina). Znajdziesz w niej:

- stan połączenia, firmware, uprawnienia użytkownika,
- surowy i sparsowany status oraz konfigurację z centrali,
- log ostatnich ramek (TX/RX), błędów i ponownych połączeń,
- przyciski **Kopiuj wszystko**, **Kopiuj log**, **Wyczyść log** i **Połącz ponownie**.

Zakładka działa także wtedy, gdy integracja nie może się połączyć. Właśnie wtedy jest najbardziej przydatna.

Jest też standardowe *Pobierz diagnostykę* na karcie integracji.

## Znane ograniczenia

- Protokół odtworzony na podstawie starszej wersji aplikacji. Jeśli twój firmware gada inaczej, wklej zrzut z zakładki diagnostyki w zgłoszeniu.
- Centrala może mieć ograniczoną liczbę jednoczesnych połączeń lokalnych. Gdy HA jest połączony, aplikacja RopamNeo może działać tylko przez RopamBridge.
- Po błędnym kodzie integracja czeka 5 minut przed kolejną próbą, żeby centrala nie zablokowała logowania.

## Licencja

MIT
