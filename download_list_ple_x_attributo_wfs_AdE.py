# -*- coding: utf-8 -*-
"""
/***************************************************************************
 WFS Catasto Agenzia delle Entrate CC BY 4.1.1
                              -------------------
        copyright            : (C) 2025 by Totò Fiandaca
        email                : pigrecoinfinito@gmail.com
 ***************************************************************************/
"""

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (QgsProcessing, QgsFeatureSink, QgsProcessingException,
                      QgsProcessingAlgorithm, QgsProcessingParameterString,
                      QgsProcessingParameterBoolean, QgsProcessingParameterVectorLayer,
                      QgsProcessingParameterFeatureSink,
                      QgsFields, QgsField, QgsFeature, QgsGeometry,
                      QgsWkbTypes, QgsPointXY, QgsProject, QgsVectorLayer,
                      QgsFeatureRequest, QgsCoordinateReferenceSystem,
                      QgsCoordinateTransform, QgsProcessingLayerPostProcessorInterface)
from qgis.utils import iface
import duckdb
from datetime import datetime
import re
import os

class DatiCatastaliAlgorithm(QgsProcessingAlgorithm):

    # Parametri
    INPUT_LAYER = 'INPUT_LAYER'
    INPUT_COMUNE = 'INPUT_COMUNE'
    INPUT_FOGLIO = 'INPUT_FOGLIO'
    INPUT_PARTICELLA = 'INPUT_PARTICELLA'
    INPUT_SEZIONE = 'INPUT_SEZIONE'  # Nuovo parametro per la sezione
    INPUT_ALL_PARTICELLE = 'INPUT_ALL_PARTICELLE'
    OUTPUT = 'OUTPUT'
    
    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return DatiCatastaliAlgorithm()

    def name(self):
        return 'ricercaparticelle'

    def displayName(self):
        return self.tr('Particelle Catastali su WFS AdE')

    def group(self):
        return self.tr('Catasto_WFS')

    def groupId(self):
        return 'Catasto_WFS'

    def shortHelpString(self):
        return self.tr("""Questo algoritmo recupera dati catastali tramite il servizio WFS dell'Agenzia delle Entrate.

<b>FUNZIONALITÀ</b>:
  - Ricerca particelle catastali per <font color='blue'>attributo</font> (comune, foglio, particella)
  - Supporta ricerca di particelle singole, multiple (lista o intervallo) e modalità download massivo (intero foglio)
  - Calcolo dell'area in m² e zoom automatico sull'ultima particella trovata
<b>PARAMETRI RICHIESTI:</b>
  - Codice o Nome Comune: puoi inserire il codice catastale (es: M011) o il nome del comune (es: VILLAROSA)
  - Se il nome del comune è presente per più particelle, scrivere il codice catastale
  - Numero foglio (es: 2) fa in automatico il padding a 4 cifre
  
<b>FORMATO PARTICELLE</b>:
  - Particella singola: "1"
  - Lista particelle: "1,2,3,45"
  - Intervallo particelle: "1-7" (scarica tutte dalla 1 alla 7)
  - Combinazioni: "1,3,5-8,10,15-20"
<b>NOTA</b>:
  - Se viene richiesta la modalità "scarica tutte le particelle", e il numero di particelle è molto elevato,
    viene mostrato un avviso per segnalare l'operazione potenzialmente lenta.

<b>ATTRIBUTI DEL LAYER:</b>
  - NATIONALCADASTRALREFERENCE: codice identificativo completo
  - ADMIN: codice Comune
  - SEZIONE: sezione censuaria
  - FOGLIO: numero del foglio
  - PARTICELLA: numero della particella
  - AREA: superficie in metro quadro (m²)  
Il risultato sarà un layer vettoriale con i poligoni delle particelle trovate.
<b>NOTA:</b>
Maggiori informazioni sul servizio WFS: <a href='https://www.agenziaentrate.gov.it/portale/cartografia-catastale-wfs'>Cartografia Catastale WFS</a>
""")

    def initAlgorithm(self, config=None):
        # Parametro per layer esistente (opzionale)
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER,
                self.tr('Layer esistente (opzionale)'),
                optional=True,
                types=[QgsProcessing.TypeVectorPolygon]
            )
        )
        # Parametri per input manuale
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_COMUNE,
                self.tr('Codice Comune o nome Comune'),
                defaultValue='M011'
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_FOGLIO,
                self.tr('Numero Foglio'),
                defaultValue='0001'
            )
        )
        
        # Aggiungiamo il parametro per la sezione
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_SEZIONE,
                self.tr('Sezione (opzionale)'),
                defaultValue='',
                optional=True
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_PARTICELLA,
                self.tr('Numero Particella (singolo, lista o intervallo)'),
                defaultValue='1'
            )
        )
        # parametro per scaricare tutte le particelle del foglio
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.INPUT_ALL_PARTICELLE,
                self.tr('Scarica tutte le particelle del foglio'),
                defaultValue=False
            )
        )

        # Ottieni il timestamp corrente nel formato desiderato
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        layer_name = f'ple_out_{timestamp}'
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr(layer_name)
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # All'inizio del metodo, inizializza le variabili
        self.last_geometry = None
        self.last_layer_id = None
        self.last_feature_id = None

        # Input parameters
        comune = self.parameterAsString(parameters, self.INPUT_COMUNE, context).strip().upper()
        foglio = self.parameterAsString(parameters, self.INPUT_FOGLIO, context).strip().zfill(4)
        sezione = self.parameterAsString(parameters, self.INPUT_SEZIONE, context).strip().upper()
        particella_input = self.parameterAsString(parameters, self.INPUT_PARTICELLA, context).strip()
        all_particelle = self.parameterAsBool(parameters, self.INPUT_ALL_PARTICELLE, context)
            
        # Feedback iniziale
        feedback.pushInfo("=== AVVIO PROCESSO DI RICERCA PARTICELLE ===")
        feedback.pushInfo(f"Comune: {comune}")
        feedback.pushInfo(f"Foglio: {foglio}")
        if sezione:
            feedback.pushInfo(f"Sezione: {sezione}")
        if all_particelle:
            feedback.pushInfo("Modalità: TUTTE LE PARTICELLE DEL FOGLIO")
        else:
            feedback.pushInfo(f"Particelle richieste: {particella_input}")

        # Gestione del layer di output o layer esistente
        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        if input_layer:
            feedback.pushInfo(f'Aggiungendo dati al layer esistente: {input_layer.name()}')
            is_gpkg = input_layer.source().lower().endswith('.gpkg')
            if is_gpkg:
                # Per Geopackage, usa una transazione esplicita
                input_layer.dataProvider().enterUpdateMode()

            sink = input_layer.dataProvider()
            dest_id = input_layer.id()

            # Non chiamare startEditing per geopackage
            if not is_gpkg:
                input_layer.startEditing()
        else:
            # Create new layer with fields
            feedback.pushInfo('Creando nuovo layer')
            fields = QgsFields()
            fields.append(QgsField('NATIONALCADASTRALREFERENCE', QVariant.String, 'string'))
            fields.append(QgsField('ADMIN', QVariant.String, 'string'))
            fields.append(QgsField('SEZIONE', QVariant.String, 'string'))
            fields.append(QgsField('FOGLIO', QVariant.String, 'string'))
            fields.append(QgsField('PARTICELLA', QVariant.String, 'string'))
            fields.append(QgsField('AREA', QVariant.Double, 'double'))
            
            # Create output sink for new layer
            (sink, dest_id) = self.parameterAsSink(
                parameters,
                self.OUTPUT,
                context,
                fields,
                QgsWkbTypes.MultiPolygon,
                QgsCoordinateReferenceSystem('EPSG:6706')
            )

            if sink is None:
                raise QgsProcessingException(self.tr('Errore nella creazione del layer di output'))

        # Recupera il file parquet
        try:
            result = self.get_parquet_file(comune, feedback)
            if not result[0]:  # file_name è None
                if result[1]:  # è multi-comune
                    feedback.pushInfo("Sono stati trovati più comuni, specificare il codice esatto.")
                else:
                    feedback.reportError(f"Nessun comune trovato per: {comune}")
                return {self.OUTPUT: dest_id}
            file_name = result[0]
        except Exception as e:
            feedback.reportError(f"Errore nel recupero del file parquet: {str(e)}")
            return {self.OUTPUT: dest_id}

        # Nella parte del processAlgorithm dove vengono chiamati i metodi
        
        # Preparazione della lista di particelle
        particelle_da_cercare = []
        
        if all_particelle:
            feedback.pushInfo("Recupero di tutte le particelle del foglio...")
            particelle_da_cercare = self.get_all_particelle(self.codice_comune, foglio, file_name, feedback, sezione)
            if not particelle_da_cercare:
                feedback.reportError(f"Nessuna particella trovata nel foglio {foglio}")
                return {self.OUTPUT: dest_id}
            if len(particelle_da_cercare) > 1000:
                feedback.pushWarning(f"Attenzione: {len(particelle_da_cercare)} particelle da scaricare. L'operazione potrebbe richiedere molto tempo.")
        else:
            # metodo per analizzare input multipli (lista o intervallo)
            particelle_da_cercare = self.parse_particelle_input(particella_input, feedback)

        total_particelle = len(particelle_da_cercare)
        particelle_non_trovate = []
        particelle_trovate = 0
        
        feedback.pushInfo(f"Inizio ricerca di {total_particelle} particelle...")

        # Loop per la ricerca di ciascuna particella
        for i, particella in enumerate(particelle_da_cercare):
            if feedback.isCanceled():
                break
            
            # Aggiorna progresso 
            progress = int((i / total_particelle) * 100)
            feedback.setProgress(progress)
            
            feedback.pushInfo(f"--- Ricerca particella {particella} ({i+1}/{total_particelle}) ---")
            # Qui dobbiamo passare anche il parametro sezione
            coordinates_list = self.get_coordinates(self.codice_comune, foglio, particella, file_name, feedback, sezione)
            if not coordinates_list:
                feedback.pushInfo(f"Particella {particella} non trovata nel database")
                particelle_non_trovate.append(particella)
                continue

            last_geometry = None
            found = False
            for coordinates in coordinates_list:
                try:
                    current_success, current_geometry = self.get_particella_wfs(coordinates[0], coordinates[1], sink, input_layer, feedback)
                    if current_success and current_geometry:
                        found = True
                        last_geometry = current_geometry
                except Exception as e:
                    feedback.pushWarning(f"Errore nelle coordinate {coordinates}: {str(e)}")
                    continue

            if found:
                particelle_trovate += 1
                self.last_geometry = last_geometry
                self.last_layer_id = dest_id
            else:
                particelle_non_trovate.append(particella)

        # Riepilogo finale
        feedback.pushInfo("\n=== RIEPILOGO OPERAZIONE ===")
        feedback.pushInfo(f"Particelle richieste: {total_particelle}")
        feedback.pushInfo(f"Particelle recuperate: {particelle_trovate}")
        if particelle_non_trovate:
            feedback.pushInfo(f"Particelle non trovate: {len(particelle_non_trovate)}")
            if len(particelle_non_trovate) <= 20:
                feedback.pushInfo(f"Elenco: {', '.join(particelle_non_trovate)}")
            else:
                feedback.pushInfo(f"Prime 20 non trovate: {', '.join(particelle_non_trovate[:20])}")
        
        # Finalizzazione del layer
        if input_layer:
            if is_gpkg:
                input_layer.dataProvider().leaveUpdateMode()
            else:
                if particelle_trovate > 0:
                    input_layer.commitChanges()
                else:
                    input_layer.rollBack()

        return {self.OUTPUT: dest_id}

    def parse_particelle_input(self, particella_input, feedback):
        """COMMENT: Analizza l'input delle particelle (singolo, lista o intervallo) e restituisce una lista di particelle.
           Questo metodo è nuovo rispetto alla versione 1."""
        particelle = []
        particella_input = particella_input.replace(" ", "")
        if "," in particella_input:
            parts = particella_input.split(",")
            for part in parts:
                if "-" in part:
                    try:
                        start, end = map(int, part.split("-"))
                        particelle.extend([str(i) for i in range(start, end + 1)])
                    except ValueError:
                        feedback.pushWarning(f"Formato non valido per l'intervallo: {part}")
                else:
                    particelle.append(part)
        elif "-" in particella_input:
            try:
                start, end = map(int, particella_input.split("-"))
                particelle = [str(i) for i in range(start, end + 1)]
            except ValueError:
                feedback.pushWarning(f"Formato non valido per l'intervallo: {particella_input}")
        else:
            particelle = [particella_input]
        return particelle

    def get_all_particelle(self, codice_comune, foglio, file_name, feedback, sezione=None):
        """Recupera tutte le particelle di un foglio tramite DuckDB."""
        feedback.pushInfo(f"Ricerca di tutte le particelle nel foglio {foglio}...")
        if sezione:
            feedback.pushInfo(f"Filtro per Sezione: {sezione}")
        
        try:
            con = duckdb.connect()
            try:
                url = f'https://raw.githubusercontent.com/ondata/dati_catastali/main/S_0000_ITALIA/anagrafica/{file_name}'
                
                if sezione and sezione.strip():
                    # Query con filtro per sezione
                    query = """
                        SELECT DISTINCT particella, INSPIREID_LOCALID
                        FROM read_parquet(?) 
                        WHERE comune = ? 
                          AND foglio LIKE ?
                          AND SUBSTR(INSPIREID_LOCALID, 16, 1) = ?
                        ORDER BY particella
                    """
                    result = con.execute(query, [url, codice_comune, foglio, sezione]).fetchall()
                    feedback.pushInfo(f"Ricerca particelle con filtro sezione: {sezione}")
                else:
                    # Query originale senza filtro per sezione
                    query = """
                        SELECT DISTINCT particella 
                        FROM read_parquet(?) 
                        WHERE comune = ? 
                          AND foglio LIKE ?
                        ORDER BY particella
                    """
                    result = con.execute(query, [url, codice_comune, foglio]).fetchall()
                
                if result and len(result) > 0:
                    particelle = [r[0] for r in result]
                    feedback.pushInfo(f"Trovate {len(particelle)} particelle nel foglio {foglio}")
                    return particelle
                else:
                    feedback.reportError(f"Nessuna particella trovata per il foglio {foglio}")
                    return []
            finally:
                con.close()
        except Exception as e:
            feedback.reportError(f"Errore nella ricerca delle particelle: {str(e)}")
            return []

    def get_parquet_file(self, comune, feedback):
        """Recupera il nome del file parquet per il comune specificato."""
        feedback.pushInfo(f"Ricerca comune: {comune}")
        try:
            con = duckdb.connect()
            try:
                query = """
                    SELECT file, comune, denominazione_it 
                    FROM 'https://raw.githubusercontent.com/ondata/dati_catastali/main/S_0000_ITALIA/anagrafica/index.parquet' 
                    WHERE comune = ? OR denominazione_it ILIKE ?
                """
                result = con.execute(query, [comune, f'%{comune}%']).fetchall()
                if not result:
                    feedback.reportError("Nessun comune trovato con il codice o nome specificato")
                    return None, False
                if len(result) > 1:
                    feedback.pushInfo("\nComuni trovati:")
                    for r in result:
                        feedback.pushInfo(f"- Codice: {r[1]}, Nome: {r[2]}")
                    feedback.pushInfo("\nINSERISCI IL CODICE ESATTO DEL COMUNE DESIDERATO.")
                    self.last_geometry = None
                    self.last_layer_id = None
                    return None, True
                file_name = result[0][0]
                self.codice_comune = result[0][1]
                nome = result[0][2]
                feedback.pushInfo(f"Comune trovato: {nome} (Codice: {self.codice_comune})")
                feedback.pushInfo(f"File associato: {file_name}")
                return file_name, False
            finally:
                con.close()
        except Exception as e:
            feedback.reportError(f"Errore durante la ricerca del comune: {str(e)}")
            return None, False
    def get_coordinates(self, comune, foglio, particella, file_name, feedback, sezione=None):
        """Recupera le coordinate per la particella specificata."""
        feedback.pushInfo(f"Ricerca coordinate per Particella {particella}, Foglio {foglio}")
        if sezione:
            feedback.pushInfo(f"Filtro per Sezione: {sezione}")
        
        try:
            con = duckdb.connect()
            try:
                url = f'https://raw.githubusercontent.com/ondata/dati_catastali/main/S_0000_ITALIA/anagrafica/{file_name}'
                
                if sezione and sezione.strip():
                    # Query con filtro per sezione
                    query = """
                        SELECT x, y, INSPIREID_LOCALID
                        FROM read_parquet(?) 
                        WHERE comune = ? 
                          AND foglio LIKE ? 
                          AND particella LIKE ?
                          AND SUBSTR(INSPIREID_LOCALID, 16, 1) = ?
                    """
                    result = con.execute(query, [url, comune, foglio, particella, sezione]).fetchall()
                    feedback.pushInfo(f"Ricerca con filtro sezione: {sezione}")
                else:
                    # Query originale senza filtro per sezione
                    query = """
                        SELECT x, y, INSPIREID_LOCALID
                        FROM read_parquet(?) 
                        WHERE comune = ? 
                          AND foglio LIKE ? 
                          AND particella LIKE ?
                    """
                    result = con.execute(query, [url, comune, foglio, particella]).fetchall()
                
                if result and len(result) > 0:
                    coordinates_list = []
                    for r in result:
                        x = float(r[0]) / 1000000
                        y = float(r[1]) / 1000000
                        inspireid = r[2]
                        sezione_trovata = inspireid[15:16] if len(inspireid) > 16 else ""
                        feedback.pushInfo(f"Coordinate trovate: X={x}, Y={y}, Sezione={sezione_trovata}")
                        coordinates_list.append((x, y))
                    if len(coordinates_list) > 1:
                        feedback.pushInfo(f"Trovate {len(coordinates_list)} istanze della particella {particella}")
                    return coordinates_list
                else:
                    feedback.pushInfo(f"Particella {particella} non trovata")
                    return None
            finally:
                con.close()
        except Exception as e:
            feedback.reportError(f"Errore durante la ricerca delle coordinate: {str(e)}")
            return None

    def get_particella_wfs(self, x, y, sink, input_layer, feedback):
        """Richiede e importa le feature WFS della particella."""
        feedback.pushInfo("Richiedo dati WFS...")
        wfs_layer = None
        try:
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
                error_msg = wfs_layer.dataProvider().error().message() if wfs_layer.dataProvider() else "Nessun dettaglio disponibile"
                feedback.reportError(f"Layer WFS non valido: {error_msg}")
                return False, None
            
            feedback.pushInfo("Layer WFS caricato con successo")
            
            # Crea un buffer intorno al punto per migliorare la ricerca
            point = QgsGeometry.fromPointXY(QgsPointXY(x, y))
            buffer_size = 0.00001  # Circa 1m in gradi decimali
            search_area = point.buffer(buffer_size, 5)

            request = QgsFeatureRequest().setFilterRect(search_area.boundingBox())
            features = list(wfs_layer.getFeatures(request))

            feedback.pushInfo(f"Features trovate: {len(features)}")

            # Get existing refs if input_layer exists
            existing_refs = set()
            if input_layer:
                existing_refs = set(feat['NATIONALCADASTRALREFERENCE'] for feat in input_layer.getFeatures())
                feedback.pushInfo(f"Riferimenti catastali esistenti: {len(existing_refs)}")
            
            # Prepara i sistemi di riferimento una sola volta
            source_crs = QgsCoordinateReferenceSystem('EPSG:6706')
            dest_crs = QgsCoordinateReferenceSystem('EPSG:3045')  # ETRS89 / UTM zone 32N
            xform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
            
            features_added = 0
            last_geometry = None

            # Ottieni i campi del layer di input se esiste
            if input_layer:
                field_names = [field.name() for field in input_layer.fields()]
                feedback.pushInfo(f"Campi del layer: {field_names}")
            
            for feat in features:
                try:
                    ref_catastale = feat['NATIONALCADASTRALREFERENCE']
                    
                    if ref_catastale in existing_refs:
                        feedback.pushInfo(f"\nNB: Particella {ref_catastale} già presente nel layer\n")
                        continue
                    
                    geom = feat.geometry()
                    if not geom or not geom.isGeosValid():
                        feedback.pushWarning(f"Geometria non valida per {ref_catastale}")
                        continue
                    
                    new_feat = QgsFeature()
                    new_feat.setGeometry(geom)
                    
                    # Calcolo area con trasformazione sicura
                    try:
                        geom_transformed = QgsGeometry(geom)
                        if geom_transformed.transform(xform) == 0:  # 0 indica successo
                            area = geom_transformed.area()
                        else:
                            area = 0
                            feedback.pushWarning(f"Errore nella trasformazione della geometria per {ref_catastale}")
                    except Exception as e:
                        area = 0
                        feedback.pushWarning(f"Errore nel calcolo dell'area per {ref_catastale}: {str(e)}")
                    
                    # Estrai i componenti dal ref_catastale in modo sicuro
                    parts = ref_catastale.split('.')
                    admin = parts[0][:4] if len(parts) > 0 and len(parts[0]) >= 4 else ''
                    sezione = parts[0][4:5] if len(parts[0]) >= 5 else ''
                    foglio = parts[0][5:9] if len(parts[0]) >= 9 else ''
                    particella = parts[-1] if len(parts) > 1 else ''
                    
                    if input_layer:
                        # Crea un dizionario degli attributi
                        attr_dict = {
                            'NATIONALCADASTRALREFERENCE': ref_catastale,
                            'ADMIN': admin,
                            'SEZIONE': sezione,
                            'FOGLIO': foglio,
                            'PARTICELLA': particella,
                            'AREA': area
                        }
                        
                        # Crea la lista degli attributi nell'ordine corretto
                        attributes = []
                        for field_name in field_names:
                            attributes.append(attr_dict.get(field_name, None))
                    else:
                        # Per nuovo layer, usa l'ordine predefinito
                        attributes = [ref_catastale, admin, sezione, foglio, particella, area]
                    
                    new_feat.setAttributes(attributes)
                    
                    if sink.addFeature(new_feat):
                        features_added += 1
                        existing_refs.add(ref_catastale)
                        last_geometry = geom
                        self.last_feature_id = new_feat.id()
                    else:
                        feedback.pushWarning(f"Impossibile aggiungere la feature {ref_catastale}")
                    
                except Exception as e:
                    feedback.pushWarning(f"Errore nell'elaborazione della feature: {str(e)}")
                    continue
            
            feedback.pushInfo(f"Aggiunte {features_added} nuove particelle")
            return True, last_geometry
            
        except Exception as e:
            feedback.reportError(f"Errore generale nel WFS: {str(e)}")
            return False, None
            
        finally:
            if wfs_layer:
                del wfs_layer

    def postProcessAlgorithm(self, context, feedback):
        """
        Gestisce lo zoom all'ultima particella importata, trasformando la geometria nel CRS del progetto.
        """
        if not hasattr(self, 'last_geometry') or not self.last_geometry:
            return {}
        
        try:
            from qgis.utils import iface
            if iface and iface.mapCanvas():
                # Sistema di riferimento della particella (EPSG:6706)
                source_crs = QgsCoordinateReferenceSystem('EPSG:6706')
                # Sistema di riferimento del progetto
                dest_crs = QgsProject.instance().crs()
                
                # Crea il trasformatore di coordinate
                transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
                
                # Copia la geometria originale
                geom = QgsGeometry(self.last_geometry)
                # Trasforma la geometria nel CRS del progetto
                geom.transform(transform)
                
                # Calcola il bounding box nel CRS del progetto
                rect = geom.boundingBox()
                
                # Calcola margine proporzionale (20%)
                width = rect.width()
                height = rect.height()
                margin = max(width, height) * 0.2
                
                # Espandi il rettangolo
                rect.setXMinimum(rect.xMinimum() - margin)
                rect.setXMaximum(rect.xMaximum() + margin)
                rect.setYMinimum(rect.yMinimum() - margin)
                rect.setYMaximum(rect.yMaximum() + margin)
                
                # Imposta l'estensione e aggiorna
                iface.mapCanvas().setExtent(rect)
                iface.mapCanvas().refresh()
                
                # Evidenzia la particella
                iface.mapCanvas().flashFeatureIds(
                    context.getMapLayer(self.last_layer_id),
                    [self.last_feature_id] if hasattr(self, 'last_feature_id') else []
                )
                
                feedback.pushInfo(f"Zoom eseguito con successo (da EPSG:6706 a {dest_crs.authid()})")
                
        except Exception as e:
            feedback.reportError(f"Errore durante lo zoom: {str(e)}")
        
        return {}

class ZoomToGeometry(QgsProcessingLayerPostProcessorInterface):
    def __init__(self, geometry):
        super().__init__()
        self.geometry = geometry

    def postProcessLayer(self, layer, context, feedback):
        if not layer or not self.geometry:
            return
            
        try:
            from qgis.utils import iface
            if iface and iface.mapCanvas():
                # Sistema di riferimento della geometria (EPSG:6706)
                geom_crs = QgsCoordinateReferenceSystem('EPSG:6706')
                
                # Assicurati che la geometria sia in EPSG:6706
                geom = QgsGeometry(self.geometry)
                if layer.crs() != geom_crs:
                    # Se necessario, trasforma la geometria in EPSG:6706
                    transform_to_6706 = QgsCoordinateTransform(layer.crs(), geom_crs, QgsProject.instance())
                    geom.transform(transform_to_6706)
                
                # Ottieni il bbox della geometria in EPSG:6706
                rect = geom.boundingBox()
                
                # Ottieni il sistema di riferimento del progetto
                project_crs = QgsProject.instance().crs()
                
                # Crea il trasformatore da EPSG:6706 al CRS del progetto
                transform = QgsCoordinateTransform(geom_crs, project_crs, QgsProject.instance())
                
                # Trasforma il bbox nel sistema di riferimento del progetto
                rect_transformed = transform.transformBoundingBox(rect)
                
                # Espandi leggermente il bbox (20%)
                rect_transformed.scale(1.2)
                
                # Imposta l'extent della mappa
                iface.mapCanvas().setExtent(rect_transformed)
                iface.mapCanvas().refresh()
                
                feedback.pushInfo(f"Zoom eseguito da EPSG:6706 a {project_crs.authid()}")
        except Exception as e:
            feedback.reportError(f"Errore durante lo zoom: {str(e)}")
