# -*- coding: utf-8 -*-
"""
/***************************************************************************
 WFS Catasto Agenzia delle Entrate CC BY 4.0
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
                      QgsProcessingParameterFeatureSink, QgsFields, QgsField,
                      QgsFeature, QgsGeometry, QgsWkbTypes, QgsPointXY,
                      QgsProject, QgsVectorLayer, QgsFeatureRequest,
                      QgsExpression, QgsExpressionContext, QgsCoordinateReferenceSystem,
                      QgsProcessingLayerPostProcessorInterface, QgsCoordinateTransform, QgsProcessingParameterFile)
from qgis.utils import iface
import duckdb
import csv
from datetime import datetime

class DatiCatastaliAlgorithm(QgsProcessingAlgorithm):

    INPUT_LAYER = 'INPUT_LAYER'
    INPUT_COMUNE = 'INPUT_COMUNE'
    INPUT_FOGLIO = 'INPUT_FOGLIO'
    INPUT_PARTICELLA = 'INPUT_PARTICELLA'
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
            - Supporta l'aggiunta a layer esistenti o la creazione di nuovi layer
            - Calcola l'area in metri quadri
            - Esegue lo zoom automatico sull'ultima particella trovata
            - Gestisce i comuni con Sezione Censuaria e scarica tutte le particelle trovate.
        
        <b>PARAMETRI RICHIESTI:</b>
            - Codice o Nome Comune: puoi inserire il codice catastale (es: M011) o il nome del comune (es: VILLAROSA)
            - Se il nome del comune è presente per più particelle, scrivere il codice catastale
            - Numero foglio (es: 2) fa in automatico il padding a 4 cifre
            - Numero particella (es: 2)
            
        ---   
        <b style="color: green">UTILIZZO FILE CSV:</b>
        È possibile effettuare ricerche multiple caricando un file CSV.
        <b style="color: green">Formato del file CSV:</b>
        <b style="color: red">⚠️ ATTENZIONE !!!</b>
        Il file CSV <span style="color: red">deve</span> contenere una riga di intestazione con <span style="color: red">esattamente</span> queste colonne:

        <pre>
        COMUNE,FOGLIO,PARTICELLA
        </pre>

        <b style="color: green">Esempio:</b>
        <pre>
        COMUNE,FOGLIO,PARTICELLA
        M011,0001,1
        M290,0005,69
        M011,0001,12
        M011,0001,13
        M011,0001,14
        M011,0001,15
        </pre>

        in cui:
        - "COMUNE": Codice catastale o nome del comune.
        - "FOGLIO": Numero del foglio (con padding automatico a 4 cifre).
        - "PARTICELLA": Numero della particella.

        Ogni riga del file CSV rappresenta una singola particella catastale da ricercare.
        
        <a href='https://github.com/JungleKiosk'>by JK</a>
        ---
        <b>ATTRIBUTI DEL LAYER:</b>
            - NATIONALCADASTRALREFERENCE: codice identificativo completo
            - ADMIN: codice Comune
            - SEZIONE: sezione censuaria
            - FOGLIO: numero del foglio
            - PARTICELLA: numero della particella
            - AREA: superficie in metro quadro (m²)
        
        Il risultato sarà un layer vettoriale con i poligoni delle particelle trovate.

        <b>NOTA:</b>
        Maggiori informazioni sul servizio WFS: <a href='https://www.agenziaentrate.gov.it/portale/cartografia-catastale-wfs'>Cartografia Catastale WFS</a>""")

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER,
                self.tr('Layer esistente (opzionale)'),
                optional=True,
                types=[QgsProcessing.TypeVectorPolygon]
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_COMUNE,
                self.tr('Codice Comune o nome Comune'),
                defaultValue='M011',
                optional=True
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_FOGLIO,
                self.tr('Numero Foglio'),
                defaultValue='0001',
                optional=True
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_PARTICELLA,
                self.tr('Numero Particella'),
                defaultValue='1',
                optional=True
            )
        )
        
         # NUOVO PARAMETRO: Inserimento multiplo da CSV (opzionale)
        self.addParameter(
            QgsProcessingParameterFile(
                'INPUT_CSV',
                self.tr('File CSV con lista particelle'),
                extension='csv',
                optional=True
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
        input_csv = self.parameterAsString(parameters, 'INPUT_CSV', context).strip()
        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)

        fields = QgsFields()
        fields.append(QgsField('NATIONALCADASTRALREFERENCE', QVariant.String))
        fields.append(QgsField('ADMIN', QVariant.String))
        fields.append(QgsField('SEZIONE', QVariant.String))
        fields.append(QgsField('FOGLIO', QVariant.String))
        fields.append(QgsField('PARTICELLA', QVariant.String))
        fields.append(QgsField('AREA', QVariant.Double))

        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            QgsWkbTypes.MultiPolygon,
            QgsCoordinateReferenceSystem('EPSG:6706')
        )

        if sink is None:
            raise QgsProcessingException('Errore creazione layer output')

        # Controlla se è stato fornito il CSV
        if input_csv:
            feedback.pushInfo(f"Elaborazione CSV: {input_csv}")

            with open(input_csv, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for idx, row in enumerate(reader):
                    comune = row['COMUNE'].strip().upper()
                    foglio = row['FOGLIO'].strip().zfill(4)
                    particella = row['PARTICELLA'].strip()

                    feedback.pushInfo(f"[{idx+1}] {comune}-{foglio}-{particella}")

                    try:
                        result = self.get_parquet_file(comune, feedback)
                        if not result[0]:
                            feedback.reportError(f"Comune '{comune}' non trovato")
                            continue
                        file_name = result[0]

                        coordinates_list = self.get_coordinates(comune, foglio, particella, file_name, feedback)
                        if not coordinates_list:
                            feedback.reportError(f"Particella '{particella}' non trovata")
                            continue

                        for coordinates in coordinates_list:
                            success, _ = self.get_particella_wfs(coordinates[0], coordinates[1], sink, None, feedback)
                            if not success:
                                feedback.pushWarning(f"Errore scaricando {comune}-{foglio}-{particella}")

                    except Exception as e:
                        feedback.reportError(f"Errore CSV riga {idx+1}: {e}")
                        continue

        else:
            # Caso input singolo, controlla che sia stato inserito almeno il comune
            comune = self.parameterAsString(parameters, self.INPUT_COMUNE, context).strip().upper()
            foglio = self.parameterAsString(parameters, self.INPUT_FOGLIO, context).strip().zfill(4)
            particella = self.parameterAsString(parameters, self.INPUT_PARTICELLA, context).strip()

            if not comune:
                raise QgsProcessingException("Inserisci un Codice Comune o carica un file CSV!")

            feedback.pushInfo(f"Elaborazione singolo input: {comune}-{foglio}-{particella}")

            try:
                result = self.get_parquet_file(comune, feedback)
                if not result[0]:
                    feedback.reportError(f"Comune '{comune}' non trovato")
                    return {self.OUTPUT: dest_id}

                file_name = result[0]

                coordinates_list = self.get_coordinates(comune, foglio, particella, file_name, feedback)
                if not coordinates_list:
                    feedback.reportError(f"Particella '{particella}' non trovata")
                    return {self.OUTPUT: dest_id}

                for coordinates in coordinates_list:
                    success, _ = self.get_particella_wfs(coordinates[0], coordinates[1], sink, input_layer, feedback)
                    if not success:
                        feedback.pushWarning(f"Errore scaricando {comune}-{foglio}-{particella}")

            except Exception as e:
                feedback.reportError(f"Errore elaborazione singolo input: {e}")

        return {self.OUTPUT: dest_id}


    def get_parquet_file(self, comune, feedback):
        """Esegue la prima query per ottenere il nome del file parquet e info sul comune"""
        feedback.pushInfo(f"Ricerca comune: {comune}")
        
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
                return None, False  # Aggiungo flag False
            
            if len(result) > 1:
                feedback.pushInfo("\nComuni trovati:")
                for r in result:
                    feedback.pushInfo(f"- Codice: {r[1]}, Nome: {r[2]}")
                feedback.pushInfo("\nINSERISCI IL CODICE ESATTO DEL COMUNE DESIDERATO.")
                self.last_geometry = None  # Resetta la geometria
                self.last_layer_id = None  # Resetta l'ID del layer
                return None, True  # Aggiungo flag True per multi-comune
            
            file_name = result[0][0]
            self.codice_comune = result[0][1]  # Salva il codice comune come attributo della classe
            nome = result[0][2]
            
            feedback.pushInfo(f"Comune trovato: {nome} (Codice: {self.codice_comune})")
            feedback.pushInfo(f"File associato: {file_name}")
            
            return file_name, False  # Aggiungo flag False
        finally:
            con.close()

    def get_coordinates(self, comune, foglio, particella, file_name, feedback):
        """Esegue la seconda query per ottenere le coordinate"""
        feedback.pushInfo(f"Ricerca coordinate in {file_name}")
        
        con = duckdb.connect()
        try:
            url = f'https://raw.githubusercontent.com/ondata/dati_catastali/main/S_0000_ITALIA/anagrafica/{file_name}'
            query = """
            SELECT x, y 
            FROM read_parquet(?) 
            WHERE comune = ? 
            AND foglio LIKE ? 
            AND particella LIKE ?
            """
            result = con.execute(query, [url, self.codice_comune, foglio, particella]).fetchall()
            
            if result and len(result) > 0:
                coordinates_list = []
                for idx, r in enumerate(result):
                    x = float(r[0]) / 1000000
                    y = float(r[1]) / 1000000
                    feedback.pushInfo(f"Particella {idx + 1}: X={x}, Y={y}")
                    coordinates_list.append((x, y))
                
                if len(coordinates_list) > 1:
                    feedback.pushInfo(f"\nSaranno scaricate tutte le {len(coordinates_list)} particelle trovate")
                
                return coordinates_list  # Restituisce tutte le coordinate
            else:
                feedback.reportError("Nessun risultato trovato per i parametri specificati")
                return None
        finally:
            con.close()

    def get_particella_wfs(self, x, y, sink, input_layer, feedback):
        """Funzione per ottenere i dati WFS della particella"""
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
        Gestisce lo zoom all'ultima particella inserita con corretta trasformazione CRS.
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