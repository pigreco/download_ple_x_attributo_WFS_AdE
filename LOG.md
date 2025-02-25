# Registro delle modifiche

## Versione 1.1.0-RC2 (25 febbraio 2025)
### Miglioramenti
- Implementato il supporto alla gestione dei comuni con sezione [#5](https://github.com/pigreco/download_ple_x_attributo_WFS_AdE/issues/5)
- Aggiunto download automatico di tutte le particelle trovate per sezione
- Migliorata la gestione delle transazioni per GeoPackage
- Ottimizzato il feedback all'utente con informazioni sulle sezioni

### Bug risolti
- Corretto il problema di gestione dei comuni con sezione
- Risolto il conflitto nelle transazioni GeoPackage

## Versione 1.0.0-RC (24 febbraio 2025)

### Funzionalità principali
- Ricerca particelle catastali tramite WFS dell'Agenzia delle Entrate
- Download automatico di tutte le particelle trovate
- Calcolo area in metri quadri
- Zoom automatico sull'ultima particella trovata

### Dettagli tecnici
- Sistema di riferimento: EPSG:6706 (RDN2008/Italy zone)
- Conversione area in EPSG:3045 (ETRS89/UTM zone 32N)
- Gestione transazioni per GeoPackage e Shapefile
- Supporto multi-sezione per comuni catastali

### Dipendenze
- QGIS >= 3.28
- DuckDB
- Accesso al servizio WFS AdE

### Note
- Le coordinate vengono recuperate da file parquet ospitati su GitHub
- La ricerca può essere effettuata per codice catastale o nome comune
- In caso di omonimia tra comuni, utilizzare il codice catastale
- Il foglio viene automaticamente completato a 4 cifre

### Bug noti
- Nessun bug noto al momento

