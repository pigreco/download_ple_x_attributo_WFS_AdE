- [Introduzione](#introduzione)
  - [Query Engine](#query-engine)
    - [Interrogare il WFS del catasto](#interrogare-il-wfs-del-catasto)
    - [Come funziona](#come-funziona)

# Introduzione

Quando il servizio WFS del catasto è stato pubblicato, nella richiesta `GetCapabilities` si leggeva che erano **abilitate** le ***query* per attributo**.<br>
Provandole però non andavano a buon fine.

Abbiamo quindi contattato l'Agenzia delle Entrate e purtroppo ci hanno comunicato che:

>sono abilitate solo le richieste in GET per GetCapabilities, DescribeFeatureType, GetFeature con il *boundig box* senza ulteriori filtri.

Ci sembrava utile trovare un'alternativa - anche soltanto parziale - e ne abbiamo parlato con l'[associazione onData](https://ondata.substack.com/), che è attenta alla valorizzazione dei dati pubblici.

A seguire la loro descrizione di come hanno abilitato il motore di *query* che consente a questo progetto di funzionare.

---

## Query Engine

Salvatore Fiandaca ci ha raccontato che avrebbe voluto poter **inserire** in un modulo QGIS il **codice catastale** di un **Comune**, il **numero** di un **foglio** e il numero di una **particella** e ottenere in *output* la **geometria** della **particella**.

Allora abbiamo pensato che sarebbe bastato costruire un motore di *query* che partendo da questi attributi, restituisse una **coppia di coordinate** con cui **interrogare** il servizio **WFS** del catasto e ottenere la geometria della particella. Perché l'**interrogazione** **spaziale** del servizio WFS è **abilitata**.

### Interrogare il WFS del catasto

Una *query* WFS di esempio ha questa struttura:

`https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php?language=ita&SERVICE=WFS&VERSION=2.0.0&TYPENAMES=CP:CadastralParcel&SRSNAME=urn:ogc:def:crs:EPSG::6706&BBOX=37.9999995,12.9999995,38.0000005,13.0000005&REQUEST=GetFeature&COUNT=100`

Se si [lancia](https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php?language=ita&SERVICE=WFS&VERSION=2.0.0&TYPENAMES=CP:CadastralParcel&SRSNAME=urn:ogc:def:crs:EPSG::6706&BBOX=37.9999995,12.9999995,38.0000005,13.0000005&REQUEST=GetFeature&COUNT=100) si hanno restituiti in XML (il formato di default) i dati delle particelle comprese nel *bounding box* definito dalle coordinate `37.9999995,12.9999995,38.0000005,13.0000005`.

```xml
<wfs:FeatureCollection
    xmlns:CP="http://mapserver.gis.umn.edu/mapserver"
    xmlns:gml="http://www.opengis.net/gml/3.2"
    xmlns:wfs="http://www.opengis.net/wfs/2.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="
        http://mapserver.gis.umn.edu/mapserver
        https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php?SERVICE=WFS&VERSION=2.0.0&REQUEST=DescribeFeatureType&TYPENAME=CP:CadastralParcel&OUTPUTFORMAT=application%2Fgml%2Bxml%3B%20version%3D3.2
        http://www.opengis.net/wfs/2.0
        http://schemas.opengis.net/wfs/2.0/wfs.xsd
        http://www.opengis.net/gml/3.2
        http://schemas.opengis.net/gml/3.2.1/gml.xsd"
    timeStamp="2025-02-23T20:26:50"
    numberMatched="1"
    numberReturned="1">

    <wfs:boundedBy>
        <gml:Envelope srsName="urn:ogc:def:crs:EPSG::6706">
            <gml:lowerCorner>37.999249 12.999534</gml:lowerCorner>
            <gml:upperCorner>38.000361 13.000943</gml:upperCorner>
        </gml:Envelope>
    </wfs:boundedBy>

    <wfs:member>
        <CP:CadastralParcel gml:id="CadastralParcel.IT.AGE.PLA.A176_003100.329">
            <gml:boundedBy>
                <gml:Envelope srsName="urn:ogc:def:crs:EPSG::6706">
                    <gml:lowerCorner>37.999249 12.999534</gml:lowerCorner>
                    <gml:upperCorner>38.000361 13.000943</gml:upperCorner>
                </gml:Envelope>
            </gml:boundedBy>

            <CP:msGeometry>
                <gml:Polygon gml:id="CadastralParcel.IT.AGE.PLA.A176_003100.329.1" srsName="urn:ogc:def:crs:EPSG::6706">
                    <gml:exterior>
                        <gml:LinearRing>
                            <gml:posList srsDimension="2">
                                38.00030250 12.99962227 38.00022463 12.99953415 37.99924858 13.00089595 37.99928465 13.00094337 38.00036148 12.99969166 38.00030250 12.99962227
                            </gml:posList>
                        </gml:LinearRing>
                    </gml:exterior>
                </gml:Polygon>
            </CP:msGeometry>

            <CP:INSPIREID_LOCALID>IT.AGE.PLA.A176_003100.329</CP:INSPIREID_LOCALID>
            <CP:INSPIREID_NAMESPACE>IT.AGE.PLA.</CP:INSPIREID_NAMESPACE>
            <CP:LABEL>329</CP:LABEL>
            <CP:NATIONALCADASTRALREFERENCE>A176_003100.329</CP:NATIONALCADASTRALREFERENCE>
            <CP:ADMINISTRATIVEUNIT>A176</CP:ADMINISTRATIVEUNIT>
        </CP:CadastralParcel>
    </wfs:member>

</wfs:FeatureCollection>

```

### Come funziona

Il motore di *query* è basato semplicemente su dei file **`parquet`** esposti in **HTTP**. Questo è possibile perché - come ha scritto Andrea Borruso - se si ha a disposizione un URL di un file `parquet` è [come avere delle API](https://aborruso.github.io/posts/duckdb-intro-csv/#%C3%A8-come-avere-delle-api).

Con un *client* come [duckdb](https://duckdb.org/) (via `cli` o via linguaggio di *scripting*) è possibile infatti lanciare delle *query* `SQL` in modo diretto a un URL di un file `parquet`.

Per avere ad esempio delle info utili sulla particella `2` del foglio `0002` del comune con codice catastale `M011`, delle particelle della regione Sicilia, è possibile lanciare:

```bash
duckdb -c "
    SELECT *
    FROM 'https://raw.githubusercontent.com/ondata/dati_catastali/main/S_0000_ITALIA/anagrafica/19_Sicilia.parquet'
    WHERE comune LIKE 'M011'
      AND foglio LIKE '0002'
      AND particella LIKE '2';
"
```

In output restituisce (si può provare [qui](https://sql-workbench.com/#queries=v0,SELECT-*-FROM-'https%3A%2F%2Fraw.githubusercontent.com%2Fondata%2Fdati_catastali%2Fmain%2FS_0000_ITALIA%2Fanagrafica%2F19_Sicilia.parquet'---where-comune-like-'M011'-and---foglio-like-'0002'-and---particella-like-'2'~)):

```
INSPIREID_LOCALID = IT.AGE.PLA.M011_000200.2
           comune = M011
           foglio = 0002
       particella = 2
                x = 14181642
                y = 37639896
```

Le **coordinate** `x` e `y` sono archiviate come **numeri interi**, per ottimizzare le dimensioni dei file `parquet`. Ma in realtà sono longitudine e latitudine espresse in gradi decimali, con 6 cifre decimali, moltiplicate per `1.000.000`. Ad esempio:

- Coordinate memorizzate: `x=14181642`, `y=37639896`
- Coordinate reali: `lon=14.181642`, `lat=37.639896`

Nell'esempio di sopra si interroga il file `19_Sicilia.parquet`, perché `M011` è un Comune siciliano. Ma se si volesse interrogare un Comune di un'altra regione e sapere quale file interrogare, è stato reso disponibile un file per rispondere a questa esigenza.<br>
Se ad esempio il Comune è `D969` (che è il codice catastale di Genova), è possibile lanciare:

```bash
duckdb -c "SELECT *
FROM 'https://raw.githubusercontent.com/ondata/dati_catastali/main/S_0000_ITALIA/anagrafica/index.parquet'
WHERE comune LIKE 'D969';"
```

In output si avrà (tra le altre cose) il nome del file da interrogare, che in questo caso è `07_Liguria.parquet`:

```
          comune = D969
            file = 07_Liguria.parquet
        CODISTAT = 010025
DENOMINAZIONE_IT = GENOVA
```

Con le coordinate `x` e `y` ottenute dalla *query* `SQL`, è possibile costruire il *bounding box* per interrogare il servizio WFS del catasto e ottenere la geometria della particella.

Queste coordinate sono state ottenute estraendole con la funzione `ST_PointOnSurface`, su tutte le particelle catastali. La funzione `ST_PointOnSurface` restituisce un punto che è garantito essere all'interno della geometria. <br>
Come file di input per generare questa coppia di coordinate abbiamo usato i file in formato `gpkg` (uno per ogni regione), generati da Salvatore Fiandaca a partire dai file `GML` messi a disposizione dall'Agenzia delle Entrate.
Per estrarre queste coordinate è stato utilizzato duckdb con l'[estensione `spatial`](https://duckdb.org/docs/extensions/spatial/overview.html).

In sintesi questo motore *query* funziona in questo modo:

- si interroga il file che fa da indice, per **farsi** **restituire** il **file da interrogare** per un determinato codice catastale comunale;
- ottenuto il nome del file, lo si **interroga** per **codice catastale comunale**, **foglio** e **particella** e **ottenere** una **coppia di coordinate** che ricade nella particella.

Da qui in poi il codice costruito da Salvatore, sfrutta la **coppia di coordinate** per fare una ***query* spaziale** al **servizio WFS**, tramite un piccolissimo **bounding box** costruito attorno a questa coppia, che restituisce la geometria della particella.
