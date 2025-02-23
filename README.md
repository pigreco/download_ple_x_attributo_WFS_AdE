# download_ple_x_attributo_WFS_AdE

![](./imgs/gui.png)

## Ricerca e download di particelle (_per attributo_) usando il WFS dell Agenzia delle Entrate.

![](./imgs/demo.gif)

**FUNZIONALITÀ**:
- Ricerca particelle catastali per attributo (comune, foglio, particella)
- Supporta l'aggiunta a layer esistenti o la creazione di nuovi layer
- Calcola l'area della particella in metri quadri
- Esegue lo zoom automatico sull'ultima particella trovata

**PARAMETRI RICHIESTI:**
- Codice o Nome Comune: puoi inserire il codice catastale (es: M011) o il nome del comune (es: VILLAROSA)
- Se cercate più volte la stessa particella non la inserisce
- Se il nome del comune è presente per più particelle chiede di scrivere il codice catastale
- Numero foglio (es: 2) fa il padding a 4 cifre
- Numero particella (es: 2)

**ATTRIBUTI DEL LAYER:**
- **_NATIONALCADASTRALREFERENCE_**: codice identificativo completo
- _**ADMIN**_: codice comune
- **_SEZIONE_**: sezione censuaria
- _**FOGLIO**_: numero del foglio
- _**PARTICELLA**_: numero della particella
- _**AREA**_: superficie in metro quadro (m²)

Il risultato sarà un layer vettoriale con i poligoni delle particelle trovate.

![](./imgs/tabella.png)

## Come installare l'algoritmo nel Processing di QGIS

- L'algoritmo funziona solo da Processing di QGIS;
- Vai su Strumenti di Processing
- `Aggiungi Script agli Strumenti...` dopo aver cliccato sull'Icona di Python:

![](./imgs/strumenti_processing.png)
- Troverai l'algoritmo nel Gruppo Script | Catasto_WFS

## Riferimenti

- [RNDT Scheda metadati](https://geodati.gov.it/geoportale/visualizzazione-metadati/scheda-metadati/?uuid=age:S_0000_ITALIA)
- [Cartografia catastale WFS](https://www.agenziaentrate.gov.it/portale/cartografia-catastale-wfs)
