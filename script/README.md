# Script di Supporto

Questa cartella contiene script di supporto per il download delle particelle catastali tramite WFS.

## Contenuto

### dl_ple_attr_wfs_AdE_fc.py

Script Python che implementa una _funzione personalizzata_ per il field calc di QGIS per recuperare le geometrie delle particelle catastali.

#### Funzionalità principali

- Funzione `get_particel_wkt()` che restituisce la geometria WKT di una particella specificando:
  - Codice comune (es: M011) o nome comune (es: VILLAROSA)
  - Numero foglio
  - Numero particella
  - Sezione (opzionale)

#### Utilizzo

1. Importare lo script in QGIS come funzione personalizzata
2. Chiamare la funzione dal calcolatore di campi:

```python
get_particel_wkt('M011', '1', '2')  # usando codice comune
get_particel_wkt('VILLAROSA', '1', '2')  # usando nome comune
get_particel_wkt('M325', '22', '51','B')  # usando codice comune e sezione
```

La funzione restituirà la geometria della particella in formato WKT (Well-Known Text).

Dipendenze
- QGIS 3.x
- libreria DuckDB
