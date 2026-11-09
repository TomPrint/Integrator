# Mid-Grator

Aplikacja Django do pobierania CSV pod adresem HTTP(S), wyboru i zmiany nazw kolumn oraz zamiany wartości. Superużytkownik zakłada konta w panelu Mid-Grator, ustawia hasło startowe i przekazuje je klientowi bezpiecznym kanałem. Klient przy pierwszym logowaniu musi ustawić własne hasło. Nie ma publicznej rejestracji, automatycznych płatności ani mechanizmu odzyskiwania hasła przez e-mail.

Strona informacyjna jest dostępna pod `/`, a logowanie pod `/login/`; kontakt otwiera program pocztowy na adres `kontakt@wickywave.pl` (aplikacja nie wysyła wiadomości). Strona nadal prosi roboty o nieindeksowanie. Logowanie i tajne linki pobierania muszą być dostępne bez sesji; panel wymaga zalogowania.

Superużytkownik po zalogowaniu trafia do panelu administratora i nie może tworzyć ani edytować własnych integracji. Podczas tworzenia klienta może opcjonalnie podać nazwę firmy, widoczną w szczegółach klienta i niezależną od danych do faktury. Tabela klientów wyświetla natomiast nazwę z danych do faktury, uzupełnianych przez klienta. Istniejące wcześniej integracje administratorów nie są automatycznie usuwane ani zatrzymywane: są widoczne osobno w panelu, gdzie można je wstrzymać, wznowić lub usunąć. Integracje klientów i ich dane pozostają bez zmian.

W szczegółach klienta administrator może edytować login, e-mail konta, nazwę firmy i dane do faktury albo trwale usunąć klienta wraz z integracjami, plikami, profilem i historią akceptacji. Klient może również usunąć własne konto w ustawieniach konta; usuwa to jego dane w portalu, historię akceptacji, integracje i ich pliki oraz wylogowuje klienta. Oba sposoby usunięcia nie obejmują dokumentów poza portalem ani kopii zapasowych; przed usunięciem należy sprawdzić obowiązki retencji. Potwierdzenie usunięcia klienta i integracji odblokowuje się po 5 sekundach; zamknięcie go resetuje licznik. Bez JavaScript usuwanie przez interfejs jest niedostępne. Odliczanie zapobiega przypadkowemu kliknięciu, ale nie jest serwerowym ograniczeniem czasu ani dodatkowym uprawnieniem.

Plan podstawowy pozwala na 2 integracje, Plus na 4. Dotychczasowe integracje ponad nowym limitem pozostają dostępne; dodanie kolejnej wymaga zejścia poniżej limitu. Administrator ręcznie ustawia plan oraz opcjonalnie daty początku i końca opłacenia. Plan testowy daje limit jednej integracji na 7 dni od aktywacji administratora; po wygaśnięciu następne uruchomienie crona usuwa integracje testowe i ich pliki, zachowuje konto klienta i zapisuje informację wyświetlaną w panelu klienta. Pobieranie pliku z testu jest blokowane od chwili wygaśnięcia. Status opłaconego planu jest informacyjny: jego wygaśnięcie nie wyłącza integracji. Powrót z Plus na podstawowy jest możliwy po zakończeniu opłaconego okresu oraz usunięciu nadmiarowych integracji do maksymalnie dwóch. Administrator może wstrzymać integrację (aktualizacja i link przestają działać) lub trwale ją usunąć wraz z plikiem i regułami; wznowienie wstrzymanej integracji przywraca ten sam link.

W stopce znajdują się polityka prywatności, regulamin B2B i ustawienia cookie. Opcjonalny Google Analytics 4 jest domyślnie wyłączony. Aby go skonfigurować, ustaw dla procesu aplikacji zmienną `GOOGLE_ANALYTICS_ID` na identyfikator pomiaru GA4 w formacie `G-...` i uruchom aplikację ponownie. Nie wstawiaj niezależnie skryptu gtag ani kontenera GTM do szablonu: omijałoby to mechanizm zgody. Skrypt Google ładuje się dopiero po zgodzie na analitykę; odmowa i wycofanie zgody wyłączają pomiar, a ustawienia można zmienić w stopce. Zgoda jest zapamiętywana w przeglądarce przez 365 dni. Reklamowe sygnały zgody pozostają wyłączone. Po zmianach zasobów statycznych uruchom `collectstatic`. Przed publikacją dokumenty prawne i konfigurację Google należy zweryfikować pod kątem rzeczywistych warunków sprzedaży, retencji, dostawców i wymogów prawnych.

Po kliknięciu nazwy użytkownika klient lub administrator może zmienić adres e-mail konta i hasło. Zmiana hasła wymaga obecnego hasła; bieżąca sesja pozostaje zalogowana, a inne sesje tracą ważność. Adres konta nie zmienia adresu do faktury i nie jest weryfikowany e-mailem. Przed dodaniem każdej integracji klient musi zapisać dane do faktury: firmę lub imię i nazwisko, adres oraz poprawny e-mail; NIP jest opcjonalny. Następnie dla każdej nowej integracji potwierdza regulamin. Aplikacja zapisuje datę, wersję SHA-256 i kopię źródła dokumentu; potwierdzenie jest jednorazowe i weryfikowane ponownie przy utworzeniu integracji. Istniejące integracje i ich linki pozostają dostępne bez tych danych i potwierdzeń. Dane do faktury i historia potwierdzeń są widoczne administratorowi w szczegółach klienta. Potwierdzenie przed integracją nie zastępuje udostępnienia regulaminu przed zawarciem umowy mailowej. Panel pokazuje rozmiar ostatniego pliku na dysku, nie zużycie RAM, i czas ostatniej mierzonej aktualizacji. Dla wcześniejszych aktualizacji czas jest nieznany. Pokazuje ostatni błąd danej integracji oraz zapisane nieobsłużone błędy żądań WWW i crona. Nie jest to pełny monitoring: błędy startu, awarie bazy lub hostingu mogą się tam nie pojawić; szczegóły pozostają w logach serwera.

## Obsługa umów i danych

Regulamin przewiduje czynności wykonywane poza aplikacją; portal nie wysyła wiadomości, nie przypomina o terminach, nie weryfikuje praw przedsiębiorcy, nie obsługuje reklamacji ani nie usuwa kont i kopii automatycznie. Przed sprzedażą prawnik powinien zweryfikować dokumenty, procesy i zastosowanie przepisów, w tym do osób prowadzących JDG oraz usług pośrednich. Należy ustalić i udokumentować rzeczywistą retencję kopii u hostingu oraz sposób usuwania danych z kopii i w razie potrzeby uzupełnić politykę prywatności; nie zakładać, że usunięcie aktywnego konta usuwa kopie zapasowe.

1. Przed zawarciem umowy wyślij klientowi wersję regulaminu możliwą do zapisania i odtworzenia, np. wyrenderowany dokument PDF, i zachowaj wysłaną kopię oraz korespondencję. Uzgodnij cenę, płatność oraz dokładny początek i koniec okresu. Potwierdzenie w panelu zapisuje surowy szablon, nie zastępuje dokumentu wysłanego przed umową ani archiwum wyrenderowanych wersji.
2. Przed przetwarzaniem danych osobowych w CSV ustal role stron; gdy wymagane jest powierzenie z art. 28 RODO, zawrzyj umowę przed przekazaniem danych. Aplikacja nie wykrywa danych osobowych ani nie blokuje ich bez umowy.
3. Przed umową sprawdź, czy klientowi prowadzącemu JDG przysługują szczególne prawa; przekaż wymagane informacje i obsłuż ewentualne odstąpienie oraz wymagane zgody przy rozpoczęciu usługi. Zapisuj zgłoszenia i odpowiadaj na reklamacje w terminie 14 dni kalendarzowych.
4. Odnowienie i zmiany planu uzgadniaj mailowo. Po zakończeniu umowy ręcznie wstrzymaj integracje, a następnie usuń dane aktywne w ciągu 30 dni, z uwzględnieniem prawnych podstaw dalszego przechowywania. Usuwanie samych integracji w panelu nie usuwa konta, korespondencji, logów ani kopii zapasowych; określ i wykonaj odrębny proces dla tych danych. Zachowuj dokumentację księgową i inne dane wymagane prawem.
5. Przed zmianą regulaminu zachowaj poprzednią i nową wyrenderowaną wersję oraz wyślij klientom nową wersję e-mailem co najmniej 30 dni przed planowanym wejściem zmian. Uwzględnij zasady obowiązywania dotychczasowych umów; automatyczny checkbox przy integracji nie jest automatycznym mechanizmem powiadomień ani dowodem wcześniejszego doręczenia dokumentu.

Bezpłatny test trwa 7 kolejnych dni od uzgodnionego uruchomienia, obejmuje jedną integrację i nie przechodzi automatycznie w płatny plan. Administrator musi ręcznie zapisać dokładny początek i koniec testu, uruchomić konto, a przed jego końcem ustalić decyzję klienta. Limit jednej integracji w teście jest warunkiem umownym: aplikacja nie rozpoznaje okresu testowego i nie egzekwuje tego limitu; administrator musi go kontrolować ręcznie. Rezygnacja w teście lub brak mailowego uzgodnienia płatnej usługi oznacza zakończenie bez opłaty: administrator ręcznie wstrzymuje integracje i usuwa aktywne dane w terminie opisanym w regulaminie. Po potwierdzeniu przez obie strony uzgadnia początek pełnego płatnego roku i termin płatności po teście. Pola „opłacone od/do” są wyłącznie informacyjne, nie służą do automatycznego naliczania testu ani wyłączenia integracji; nie należy oznaczać bezpłatnego okresu jako opłaconego. Aplikacja nie przypomina o końcu testu i nie egzekwuje jego zakończenia.

## Działanie

1. Użytkownik podaje adres hurtowni i nazwę integracji.
2. Aplikacja sprawdza pełny adres z `https://` lub `http://`, pobiera źródło oraz wykrywa separator i kolumny. Błędy pobrania lub rozpoznania CSV są pokazywane przy adresie; jawna strona HTML jest odrzucana. Samo rozpoznanie nagłówka nie gwarantuje poprawności całej zawartości — ta jest sprawdzana w kolejnym kroku. Dozwolone kodowania: UTF-8 (również z BOM) i Windows-1250.
3. Na ekranie reguł użytkownik wybiera częstotliwość (2, 4, 8, 12, 24, 48 lub 168 godzin) oraz separator wynikowego CSV: jak w źródle, średnik, przecinek, tabulator lub pionową kreskę. Plik źródłowy o rozmiarze co najmniej 5 MiB można aktualizować nie częściej niż co 24 godziny. Jeśli plik osiągnie próg po konfiguracji, system zapisze interwał 24 godzin i pokaże informację w panelu; gdy od poprzedniej próby nie minęły 24 godziny, cron odłoży przetworzenie. Cron musi najpierw pobrać plik, aby wykryć jego wzrost. Zmiana dotyczy także istniejących integracji. Jeśli plik później zmaleje, interwał nie zostanie automatycznie skrócony. Limit częstotliwości nie ogranicza ręcznego sprawdzania i publikowania. Przy opcji źródłowej pokazany jest separator wykryty podczas ostatniego odczytu pliku; jeśli później źródło go zmieni, wynik również użyje nowego separatora. Domyślnie zachowywany jest separator źródła, również dla wcześniej utworzonych integracji. Zmiany w edycji zaczynają obowiązywać po zatwierdzeniu i opublikowaniu pliku. Użytkownik wybiera kolumny, nazwy wyjściowe i opcjonalnie reguły dokładnych zamian. Wartości są traktowane jako tekst: `1` i `1.0` to różne wartości; spacje i wielkość liter mają znaczenie. Kolumna bez reguł pozostaje bez zmian. Jeśli kolumna ma reguły, każda napotkana wartość musi mieć dopasowanie.
   Można też dodać reguły liczbowe `<`, `<=`, `=`, `>` i `>=`, np. `>= 10 → Duża ilość` i `< 10 → Mała ilość`. Progi i wartości są porównywane jako liczby dziesiętne (kropka lub przecinek, opcjonalny znak); wynik to dowolny tekst. Najpierw stosowana jest dokładna zamiana, następnie pierwsza pasująca reguła liczbowa od góry. Wartość nieliczbowa bez dokładnego dopasowania lub liczba bez pasującej reguły powoduje błąd i pozostawia ostatni poprawny plik. Reguły można wpisać w kreatorze albo bez JavaScript jako JSON, np. `[{"operator":">=","threshold":"10","result":"Duża ilość"}]`.

   Osobna reguła pieniężna powiększa lub pomniejsza każdą wartość liczbową w wybranej kolumnie o podany nieujemny procent. Akceptuje kropkę lub przecinek w źródle i procentach; wynik ma dwie cyfry po kropce, z zaokrągleniem połówek od zera (`ROUND_HALF_UP`). Pomniejszenie o więcej niż 100% może dać wynik ujemny. Nie można jej łączyć z innymi regułami tej kolumny. Niepoprawna wartość blokuje publikację i pozostawia ostatni poprawny plik.

   Dla nowych reguł wybiera się jeden rodzaj na kolumnę: prostą zamianę, porównanie liczbowe albo regułę pieniężną. Wcześniej zapisane połączenie prostej zamiany i porównań nadal działa i można je zachować bez zmian; aby zmienić te reguły, wybierz jeden rodzaj.
4. Przycisk sprawdzenia weryfikuje cały aktualny plik i pokazuje pierwszych 10 wierszy. Potwierdzenie ponownie pobiera i sprawdza źródło; dopiero po powodzeniu publikuje plik i aktywuje integrację.
5. Cron aktualizuje aktywne integracje, gdy upłynie ich interwał. Oczekujące integracje przetwarzane są pojedynczo, najpierw według najwcześniejszego terminu; integracje bez terminu są pierwsze. Jedna globalna blokada zapobiega nakładaniu uruchomień crona, a osobna blokada chroni integrację przed jednoczesną publikacją. Planowany termin to czas ostatniej próby (lub ostatniego sukcesu, jeśli próby nie zapisano) powiększony o interwał. Panel pokazuje opóźnienie ostatniej udanej automatycznej aktualizacji, gdy przekroczyło 15 minut: od planowanego terminu do zakończenia publikacji, włącznie z czasem pobierania i przetwarzania. Opóźnienie może wynikać z kolejki, harmonogramu crona, niedostępności hostingu lub innych przyczyn; nie jest pomiarem samego czasu oczekiwania ani diagnozą przyczyny. Dla wcześniejszych aktualizacji lub braku znanego terminu opóźnienie jest nieznane. Ręczna publikacja usuwa wcześniejszy komunikat. Błąd jest widoczny w panelu i logu, a poprzedni poprawny plik i informacja o ostatnim sukcesie zostają zachowane. Ponowna próba nastąpi po upływie interwału od ostatniej próby.

Pobieranie i przetwarzanie korzysta z plików tymczasowych i przetwarza dane porcjami, co ogranicza użycie pamięci. Wymaga to wolnego miejsca w systemowym katalogu tymczasowym oraz w katalogu prywatnym, także na jednoczesne przechowywanie starego i nowego wyniku. Pliki tymczasowe są usuwane po normalnym zakończeniu lub błędzie; po nagłym przerwaniu procesu mogą pozostać pliki w katalogu wyników. Operacje sprawdzenia i potwierdzenia nadal wykonują się w żądaniach WWW, więc większa liczba użytkowników może równocześnie obciążać hosting. Nie ma jeszcze kolejki zadań dla panelu.

CSV wynikowy jest kodowany jako UTF-8 z BOM i używa wybranego separatora; opcja domyślna używa separatora wykrytego w aktualnym źródle. Sprawdź zgodność kodowania, separatora, kolumn i długiego czasu odpowiedzi z konkretną konfiguracją e-Integrator przed uruchomieniem produkcyjnym. Źródło musi odpowiadać bezpośrednio kodem 200: przekierowania, logowanie i zasoby sieci prywatnej nie są obsługiwane. Limit pliku wejściowego i wyjściowego wynosi 20 MiB, liczby kolumn 200, wierszy danych 200 000. Pusty plik danych blokuje aktualizację.

Pobierany plik otrzymuje nazwę `login_nazwa-integracji.csv` według loginu właściciela i nazwy integracji, oddzielonych znakiem `_`. Spacje są zastępowane podkreśleniami, a znaki niedozwolone w nazwach plików usuwane. Nazwa pliku na dysku serwera pozostaje osobna.

## Wdrożenie na MyDevil

MyDevil opisuje [Django przez Passenger](https://pomoc.mydevil.net/Django/), [Pythona i virtualenv](https://pomoc.mydevil.net/Python/) oraz [cron](https://pomoc.mydevil.net/Cron/). Wersja Django 5.2 obsługuje Python 3.10–3.14; poniższy przykład używa `python3.12`. Zależności aplikacji to Django, python-dotenv i django-tailwind oraz ich zależności instalowane jako pakiety Python; nie wymaga ona sterowników bazy ani pandas. Node.js i npm są potrzebne tylko lokalnie do przebudowy CSS, a nie do uruchomienia aplikacji na MyDevil. SQLite jest odpowiedni na początek przy małym obciążeniu; należy sprawdzić limity konta i monitorować blokady bazy przy wzroście ruchu.

1. Włącz Binexec, przygotuj virtualenv i stronę typu Python z interpreterem virtualenv zgodnie z dokumentacją MyDevil.
2. Umieść projekt (wraz z `manage.py` i `passenger_wsgi.py`) w `/usr/home/LOGIN/domains/DOMENA/public_python`. Nie umieszczaj prywatnych danych w katalogu `public`, który serwer udostępnia bezpośrednio.
3. Zainstaluj zależności i przygotuj prywatny katalog:

   ```sh
   cd /usr/home/LOGIN/domains/DOMENA/public_python
   /usr/home/LOGIN/.virtualenvs/integrator/bin/python -m pip install -r requirements.txt
   mkdir -p /usr/home/LOGIN/integrator-private
   chmod 700 /usr/home/LOGIN/integrator-private
   ```

4. Nie kopiuj lokalnego `.env` na serwer: zawiera `DEBUG=1` i klucz deweloperski. Ustaw zmienne środowiskowe zarówno dla Passengera, jak i dla poleceń administracyjnych oraz cron. MyDevil dokumentuje zmienne Passengera w `~/.bash_profile`; cron nie musi go wczytywać, więc poniżej jawnie korzysta z osobnego pliku. Chroń plik środowiskowy (`chmod 600`) i nie umieszczaj go w publicznym katalogu ani repozytorium. Przykład zawartości `/usr/home/LOGIN/integrator.env`, z wartościami dostosowanymi do domeny:

   ```sh
   export DJANGO_SECRET_KEY='TU_WSTAW_DLUGI_LOSOWY_SEKRET'
   export DJANGO_ALLOWED_HOSTS='integrator.example.pl'
   export DJANGO_CSRF_TRUSTED_ORIGINS='https://integrator.example.pl'
   export INTEGRATOR_PRIVATE_DIR='/usr/home/LOGIN/integrator-private'
   export DEBUG=0
   ```

   Wygeneruj unikalny klucz np. poleceniem `/usr/home/LOGIN/.virtualenvs/integrator/bin/python -c "import secrets; print(secrets.token_urlsafe(64))"`. Ustaw te same wartości dla Passengera zgodnie z dokumentacją hostingu. Nie publikuj klucza ani pliku środowiskowego. Włącz HTTPS na domenie. Aplikacja ustawia bezpieczne ciasteczka w trybie produkcyjnym.
5. Uruchom migracje, zbierz statyczne zasoby panelu administratora i załóż konto administratora:

   ```sh
   . /usr/home/LOGIN/integrator.env
   cd /usr/home/LOGIN/domains/DOMENA/public_python
   /usr/home/LOGIN/.virtualenvs/integrator/bin/python manage.py migrate
   /usr/home/LOGIN/.virtualenvs/integrator/bin/python manage.py collectstatic --noinput
   /usr/home/LOGIN/.virtualenvs/integrator/bin/python manage.py createsuperuser
   /usr/home/LOGIN/.virtualenvs/integrator/bin/python manage.py check --deploy
   ```

6. Zaloguj się jako superużytkownik przez `/login/` i utwórz klientów w panelu `/control/`. Przekaż hasła startowe bezpiecznie; klient zostanie poproszony o ich zmianę. Panel Django pod `/admin/` nie jest udostępniony.
7. Dodaj w panelu MyDevil zadanie cron wykonywane np. co 15 minut. Jeden proces sprawdzi terminy wszystkich integracji; nie potrzeba osobnego crona dla każdej. Zastąp `LOGIN` i `DOMENA`:

   ```cron
   */15 * * * * /bin/sh -c '. /usr/home/LOGIN/integrator.env; cd /usr/home/LOGIN/domains/DOMENA/public_python && /usr/home/LOGIN/.virtualenvs/integrator/bin/python manage.py update_integrations' >> /usr/home/LOGIN/integrator-cron.log 2>&1
   ```

   Aktualizacja rozpoczyna się przy kolejnym uruchomieniu crona po upływie interwału; opóźnienie może przekroczyć 15 minut, jeśli zadania długo trwają. To samo zadanie sprawdza wygaśnięcie planów testowych, usuwa ich integracje i pliki oraz odnotowuje zakończenie widoczne klientowi w panelu. Blokada globalna pomija kolejne uruchomienie crona, gdy poprzednie nadal działa (informacja trafia do logu); blokada integracji zapobiega równoczesnej aktualizacji tej samej integracji z panelu i crona. Wymagany jest wspólny lokalny system plików dla procesów aplikacji i crona. Sprawdzaj log crona i komunikaty w panelu; e-mailowe powiadomienia nie są zaimplementowane.
8. Uruchom ponownie aplikację poleceniem `devil www restart DOMENA`. Sprawdź pierwsze pobranie z Comarch, działanie crona i błąd źródła.

## Style Tailwind

Projekt używa `django-tailwind`. Źródło stylów znajduje się w `theme/static_src/src/styles.css`, a gotowy plik `theme/static/css/dist/styles.css` należy wdrożyć wraz z projektem. Na serwerze wystarczy wykonać opisane wyżej `collectstatic`; nie uruchamiaj `tailwind install` ani `tailwind build` na MyDevil.

Aby zmienić wygląd lokalnie, potrzebujesz Node.js i npm. Po instalacji zależności Python uruchom w katalogu projektu:

```powershell
.\.venv\Scripts\python.exe manage.py tailwind install
.\.venv\Scripts\python.exe manage.py tailwind build
```

Po każdej zmianie szablonów lub źródłowego CSS zbuduj ponownie plik i prześlij go na serwer. Katalog `theme/static_src/node_modules` służy wyłącznie do lokalnego budowania; można go usunąć i odtworzyć poleceniem `tailwind install`.

## Bezpieczeństwo i kopie

Tajny adres pobierania jest hasłem dostępu do pliku, nie kontem użytkownika. Nie wysyłaj go publicznie; można go unieważnić w panelu. `robots.txt` i `noindex` nie są zabezpieczeniem. Adresy mogą pojawić się w logach dostępu serwera lub systemów pośrednich — ogranicz dostęp i retencję logów oraz, jeśli to możliwe, wyłącz zapisywanie tokenu. Panel i link wymagają HTTPS.

Regularnie wykonuj kopie katalogu prywatnego, w tym SQLite i plików CSV, oraz sekretnego klucza i konfiguracji, w bezpiecznym miejscu. Dla bazy SQLite wykonuj spójne kopie przez mechanizm backup SQLite, nie kopiuj aktywnego pliku bez uwzględnienia jego stanu. Należy też skonfigurować ochronę przed atakami na logowanie (np. limitowanie żądań na poziomie hostingu), monitoring, powiadomienia i testy odtwarzania kopii. To nie jest jeszcze kompletne rozwiązanie komercyjne SaaS: przed udostępnieniem klientom wymagany jest przegląd bezpieczeństwa i konfiguracji hostingu.

## Testy lokalne

Lokalny `.env` jest automatycznie wczytywany przez Django; zmienne ustawione w środowisku mają przed nim pierwszeństwo. Utwórz w nim indywidualny `DJANGO_SECRET_KEY`, ustaw `DEBUG=1` wyłącznie lokalnie i nie dodawaj tego pliku do repozytorium. Zainstaluj zależności i uruchom `python manage.py test integrations`. Do lokalnej bazy utwórz katalog `private`, wykonaj `python manage.py migrate`, `python manage.py createsuperuser` i `python manage.py runserver`.
