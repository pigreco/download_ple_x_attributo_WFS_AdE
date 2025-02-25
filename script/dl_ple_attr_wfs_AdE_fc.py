# -*- coding: utf-8 -*-
"""
/***************************************************************************
 WFS Catasto Agenzia delle Entrate CC BY 4.0
                              -------------------
        copyright            : (C) 2025 by Totò Fiandaca
        email                : pigrecoinfinito@gmail.com
 ***************************************************************************/
"""

from qgis.core import QgsGeometry, QgsPointXY, QgsVectorLayer, QgsFeatureRequest
import duckdb
from functools import lru_cache

@lru_cache(maxsize=128)
def get_comune_info(comune):
    """
    Recupera le informazioni sul comune dal file parquet di anagrafica.
    Implementa caching per evitare query ripetute.
    
    Args:
        comune (str): Codice o nome del comune
    
    Returns:
        tuple: (file_name, codice_comune, nome_comune) o None se non trovato
    """
    con = duckdb.connect(':memory:')
    comune = comune.strip().upper()
    
    query = """
    SELECT file, comune, denominazione_it 
    FROM 'https://raw.githubusercontent.com/ondata/dati_catastali/main/S_0000_ITALIA/anagrafica/index.parquet' 
    WHERE comune = ? OR denominazione_it ILIKE ? 
    """
    
    result = con.execute(query, [comune, f'%{comune}%']).fetchall()
    con.close()
    
    if not result:
        return None
    if len(result) > 1:
        return "multiple", result
    
    return result[0]

@qgsfunction(args='auto', group='Catasto AdE')
def get_particel_wkt(comune, foglio, particella, sezione=None, feature=None, parent=None):
    """
    Restituisce la geometria di una particella catastale in formato WKT a partire dal comune, foglio e particella.
    
    <h2>Esempio di utilizzo:</h2>
    <ul>
      <li>get_particella_wkt('M011', '1', '2') -> geometria WKT della particella</li>
      <li>get_particella_wkt('VILLAROSA', '1', '2') -> geometria WKT usando il nome comune</li>
      <li>get_particella_wkt('M325', '22', '51','B') -> geometria WKT usando il codice comune e sezione</li>
    </ul>
    """
    try:
        # Normalizza i parametri
        foglio = str(foglio).strip().zfill(4)
        particella = str(particella).strip()
        sezione_filtro = sezione.strip().upper() if sezione else None
        
        # Step 1: Ottieni il file parquet associato al comune
        comune_result = get_comune_info(comune)
        
        if comune_result is None:
            return "ERRORE: Nessun comune trovato con il codice o nome specificato"
        
        if comune_result == "multiple":
            comuni_trovati = ", ".join([f"{r[1]} ({r[2]})" for r in comune_result[1]])
            return f"ERRORE: Più comuni trovati. Specificare il codice esatto tra: {comuni_trovati}"
        
        file_name, codice_comune, _ = comune_result
        
        # Step 2: Ottieni le coordinate X,Y della particella
        con = duckdb.connect(':memory:')
        url = f'https://raw.githubusercontent.com/ondata/dati_catastali/main/S_0000_ITALIA/anagrafica/{file_name}'
        
        # Prepara la query di base
        base_query = """
        SELECT x, y 
        FROM read_parquet(?) 
        WHERE comune = ? 
        AND foglio LIKE ?
        AND particella LIKE ?
        """
        params = [url, codice_comune, foglio, particella]
        
        # Modifica la query se è specificata la sezione
        if sezione_filtro:
            base_query = """
            SELECT x, y 
            FROM (
                SELECT *, 
                       SUBSTR(INSPIREID_LOCALID, 16, 1) AS sezione_censuaria
                FROM read_parquet(?) 
                WHERE comune = ? 
                AND foglio LIKE ?
                AND particella LIKE ?
            ) WHERE sezione_censuaria = ?
            """
            params.append(sezione_filtro)
        
        result = con.execute(base_query, params).fetchall()
        con.close()
        
        if not result:
            return "ERRORE: Nessuna particella trovata con i parametri specificati"
        
        # Coordinate per la prima particella trovata
        x = float(result[0][0]) / 1000000
        y = float(result[0][1]) / 1000000
        
        # Step 3: Interroga il servizio WFS per ottenere la geometria
        base_url = 'https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php'
        uri = (f"pagingEnabled='true' "
               f"preferCoordinatesForWfsT11='false' "
               f"restrictToRequestBBOX='1' "
               f"srsname='EPSG:6706' "
               f"typename='CP:CadastralParcel' "
               f"url='{base_url}' "
               f"version='2.0.0' "
               f"language='ita'")
        
        wfs_layer = QgsVectorLayer(uri, "catasto_query_temp", "WFS")
        
        if not wfs_layer.isValid():
            return "ERRORE: Connessione al servizio WFS fallita"
        
        # Crea un buffer intorno al punto per migliorare la ricerca
        point = QgsGeometry.fromPointXY(QgsPointXY(x, y))
        buffer_size = 0.00001  # Circa 1m in gradi decimali
        search_area = point.buffer(buffer_size, 5)
        
        request = QgsFeatureRequest().setFilterRect(search_area.boundingBox())
        
        # Definiamo una funzione helper per controllare la corrispondenza
        def match_feature(feat):
            ref_catastale = feat['NATIONALCADASTRALREFERENCE']
            parts = ref_catastale.split('.')
            
            if len(parts) < 2 or len(parts[0]) < 9:
                return False
                
            admin_code = parts[0][:4]
            sezione_code = parts[0][4:5]
            foglio_code = parts[0][5:9]
            particella_code = parts[-1]
            
            # Verifica base
            if admin_code != codice_comune or foglio_code != foglio or particella_code != particella:
                return False
                
            # Verifica sezione se specificata
            if sezione_filtro and sezione_code != sezione_filtro:
                return False
                
            return True
        
        # Cerca la feature corrispondente
        for feat in wfs_layer.getFeatures(request):
            if match_feature(feat):
                geom = feat.geometry()
                if geom and geom.isGeosValid():
                    return geom.asWkt()
        
        return "ERRORE: Geometria non trovata o non valida"
        
    except Exception as e:
        return f"ERRORE: {str(e)}"