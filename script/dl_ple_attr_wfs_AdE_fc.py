# -*- coding: utf-8 -*-
"""
/***************************************************************************
 WFS Catasto Agenzia delle Entrate CC BY 4.0
                              -------------------
        copyright            : (C) 2025 by Totò Fiandaca
        email                : pigrecoinfinito@gmail.com
 ***************************************************************************/
"""

from qgis.core import *
from qgis.gui import *
import duckdb
import traceback

@qgsfunction(args='auto', group='Catasto AdE')
def get_particella_wkt(comune, foglio, particella, feature, parent):
    """
    Restituisce la geometria di una particella catastale in formato WKT a partire dal comune, foglio e particella.
    
    <h2>Esempio di utilizzo:</h2>
    <ul>
      <li>get_particella_wkt('M011', '1', '2') -> geometria WKT della particella</li>
      <li>get_particella_wkt('VILLAROSA', '1', '2') -> geometria WKT usando il nome comune</li>
    </ul>
    """
    try:
        # Step 1: Normalizza i parametri di input
        comune = str(comune).strip().upper()
        foglio = str(foglio).strip().zfill(4)  # Padding a 4 cifre
        particella = str(particella).strip()
        
        # Step 2: Ottieni il file parquet dal comune
        file_name, codice_comune = get_parquet_file(comune)
        if not file_name:
            return None
        
        # Step 3: Ottieni le coordinate
        x, y = get_coordinates(codice_comune, foglio, particella, file_name)
        if not x or not y:
            return None
        
        # Step 4: Ottieni la geometria dal servizio WFS
        geometry = get_particella_wfs(x, y)
        if not geometry:
            return None
        
        # Step 5: Converti la geometria in WKT
        return geometry.asWkt()
    
    except Exception as e:
        # Cattura qualsiasi errore e restituisci None
        return None

def get_parquet_file(comune):
    """Esegue la query per ottenere il nome del file parquet e info sul comune"""
    con = duckdb.connect(':memory:')
    try:
        query = """
        SELECT file, comune, denominazione_it 
        FROM 'https://raw.githubusercontent.com/ondata/dati_catastali/main/S_0000_ITALIA/anagrafica/index.parquet' 
        WHERE comune = ? OR denominazione_it ILIKE ? 
        """
        
        result = con.execute(query, [comune, f'%{comune}%']).fetchall()
        
        if not result:
            return None, None
        
        if len(result) > 1:
            # Caso multi-comune, prova a trovare una corrispondenza esatta
            for r in result:
                if r[1] == comune or r[2].upper() == comune:
                    return r[0], r[1]
            # Se nessuna corrispondenza esatta, prendi il primo risultato
            return result[0][0], result[0][1]
        
        return result[0][0], result[0][1]
    finally:
        con.close()

def get_coordinates(codice_comune, foglio, particella, file_name):
    """Esegue la query per ottenere le coordinate"""
    con = duckdb.connect(':memory:')
    try:
        url = f'https://raw.githubusercontent.com/ondata/dati_catastali/main/S_0000_ITALIA/anagrafica/{file_name}'
        query = """
        SELECT x, y 
        FROM read_parquet(?) 
        WHERE comune = ? 
        AND foglio LIKE ? 
        AND particella LIKE ?
        """
        result = con.execute(query, [url, codice_comune, foglio, particella]).fetchall()
        
        if result and len(result) > 0:
            x = float(result[0][0]) / 1000000
            y = float(result[0][1]) / 1000000
            return x, y
        else:
            return None, None
    finally:
        con.close()

def get_particella_wfs(x, y):
    """Funzione per ottenere i dati WFS della particella"""
    base_url = 'https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php'
    uri = (f"pagingEnabled='true' "
           f"preferCoordinatesForWfsT11='false' "
           f"restrictToRequestBBOX='1' "
           f"srsname='EPSG:6706' "
           f"typename='CP:CadastralParcel' "
           f"url='{base_url}' "
           f"version='2.0.0' "
           f"language='ita'")
    
    wfs_layer = QgsVectorLayer(uri, "catasto_query", "WFS")
    
    if not wfs_layer.isValid():
        return None
    
    # Crea un buffer intorno al punto per migliorare la ricerca
    point = QgsGeometry.fromPointXY(QgsPointXY(x, y))
    buffer_size = 0.00001  # Circa 1m in gradi decimali
    search_area = point.buffer(buffer_size, 5)
    
    request = QgsFeatureRequest().setFilterRect(search_area.boundingBox())
    features = list(wfs_layer.getFeatures(request))
    
    if not features:
        return None
    
    # Prendi la prima geometria valida trovata
    for feat in features:
        geom = feat.geometry()
        if geom and geom.isGeosValid():
            return geom
    
    return None