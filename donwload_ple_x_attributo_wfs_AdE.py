# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (QgsProcessing, QgsFeatureSink, QgsProcessingException,
                      QgsProcessingAlgorithm, QgsProcessingParameterString,
                      QgsProcessingParameterBoolean, QgsProcessingParameterVectorLayer,
                      QgsProcessingParameterFeatureSink, QgsFields, QgsField,
                      QgsFeature, QgsGeometry, QgsWkbTypes, QgsPointXY,
                      QgsProject, QgsVectorLayer, QgsFeatureRequest,
                      QgsExpression, QgsExpressionContext, QgsCoordinateReferenceSystem,
                      QgsProcessingLayerPostProcessorInterface, QgsCoordinateTransform)
from qgis.utils import iface
import duckdb
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
        return self.tr('Ricerca Particelle Catastali')

    def group(self):
        return self.tr('Catasto')

    def groupId(self):
        return 'catasto'

    def shortHelpString(self):
        return self.tr("""Questo algoritmo recupera dati catastali tramite il servizio WFS dell'Agenzia delle Entrate.

        <b>FUNZIONALITÀ</b>:
            - Ricerca particelle catastali per attributo (comune, foglio, particella)
            - Supporta l'aggiunta a layer esistenti o la creazione di nuovi layer
            - Calcola l'area in metri quadri
            - Esegue lo zoom automatico sull'ultima particella trovata
            - Gestisce correttamente i sistemi di coordinate (EPSG:6706 -> EPSG:3045)
        
        <b>PARAMETRI RICHIESTI:</b>
            - Codice o Nome Comune: puoi inserire il codice catastale (es: M011) o il nome del comune (es: VILLAROSA)
            - Numero foglio (es: 2) fa il padding a 4 cifre
            - Numero particella (es: 2)
        
        <b>ATTRIBUTI DEL LAYER:</b>
            - NATIONALCADASTRALREFERENCE: codice identificativo completo
            - ADMIN: codice comune
            - SEZIONE: sezione censuaria
            - FOGLIO: numero del foglio
            - PARTICELLA: numero della particella
            - AREA: <font color='red'>superficie in metri quadri</font>
        
        Il risultato sarà un layer vettoriale con i poligoni delle particelle trovate.""")

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
                defaultValue='M011'
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_FOGLIO,
                self.tr('Numero Foglio'),
                defaultValue='0002'
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_PARTICELLA,
                self.tr('Numero Particella'),
                defaultValue='2'
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Layer Particelle')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # All'inizio del metodo, inizializza le variabili
        self.last_geometry = None
        self.last_layer_id = None

        # Input parameters
        comune = self.parameterAsString(parameters, self.INPUT_COMUNE, context).strip().upper()
        foglio = self.parameterAsString(parameters, self.INPUT_FOGLIO, context).strip().zfill(4)
        particella = self.parameterAsString(parameters, self.INPUT_PARTICELLA, context).strip()
        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)

        if input_layer:
            # Use existing layer
            feedback.pushInfo(f'Aggiungendo dati al layer esistente: {input_layer.name()}')
            
            sink = input_layer.dataProvider()
            dest_id = input_layer.id()
            
            # Assicuriamoci che il layer sia in modalità editing
            input_layer.startEditing()
        else:
            # Create new layer with fields
            feedback.pushInfo('Creando nuovo layer')
            fields = QgsFields()
            fields.append(QgsField('NATIONALCADASTRALREFERENCE', QVariant.String))
            fields.append(QgsField('ADMIN', QVariant.String))
            fields.append(QgsField('SEZIONE', QVariant.String))
            fields.append(QgsField('FOGLIO', QVariant.String))
            fields.append(QgsField('PARTICELLA', QVariant.String))
            fields.append(QgsField('AREA', QVariant.Double))
            
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
            file_name = self.get_parquet_file(comune, feedback)
            if not file_name:
                return {self.OUTPUT: dest_id}
        except Exception as e:
            feedback.reportError(f"Errore nel recupero del file parquet: {str(e)}")
            return {self.OUTPUT: dest_id}

        # Recupera le coordinate
        try:
            coordinates = self.get_coordinates(comune, foglio, particella, file_name, feedback)
            if not coordinates:
                return {self.OUTPUT: dest_id}
        except Exception as e:
            feedback.reportError(f"Errore nel recupero delle coordinate: {str(e)}")
            return {self.OUTPUT: dest_id}

        # Recupera i dati WFS
        try:
            success, last_geometry = self.get_particella_wfs(coordinates[0], coordinates[1], sink, input_layer, feedback)
            if not success:
                feedback.reportError(self.tr('Errore nel recupero dei dati WFS'))
            else:
                if input_layer:
                    input_layer.commitChanges()
            
                # Salva l'ultima geometria e l'ID del layer per il post-processing
                if last_geometry:
                    self.last_geometry = last_geometry
                    self.last_layer_id = dest_id
                    feedback.pushInfo("Zoom programmato sull'ultima particella")
                
        except Exception as e:
            feedback.reportError(f"Errore nel recupero dei dati WFS: {str(e)}")
            if input_layer:
                input_layer.rollBack()

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
                return None
            
            if len(result) > 1:
                feedback.pushInfo("\nComuni trovati:")
                for r in result:
                    feedback.pushInfo(f"- Codice: {r[1]}, Nome: {r[2]}")
                feedback.pushInfo("\nInserisci il codice esatto del comune desiderato.")
                return None
            
            file_name = result[0][0]
            self.codice_comune = result[0][1]  # Salva il codice comune come attributo della classe
            nome = result[0][2]
            
            feedback.pushInfo(f"Comune trovato: {nome} (Codice: {self.codice_comune})")
            feedback.pushInfo(f"File associato: {file_name}")
            
            return file_name
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
            # Usa il codice comune salvato invece del parametro comune
            result = con.execute(query, [url, self.codice_comune, foglio, particella]).fetchall()
            
            if result and len(result) > 0:
                x = float(result[0][0]) / 1000000
                y = float(result[0][1]) / 1000000
                feedback.pushInfo(f"Coordinate trovate: X={x}, Y={y}")
                return x, y
            else:
                feedback.reportError("Nessun risultato trovato per i parametri specificati")
                return None
        finally:
            con.close()

    def get_particella_wfs(self, x, y, sink, input_layer, feedback):
        """Funzione per ottenere i dati WFS della particella"""
        feedback.pushInfo("Richiedo dati WFS...")
        
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
        
        point = QgsGeometry.fromPointXY(QgsPointXY(x, y))
        request = QgsFeatureRequest().setFilterRect(point.boundingBox())
        features = list(wfs_layer.getFeatures(request))
        
        feedback.pushInfo(f"Features trovate: {len(features)}")
        
        # Get existing refs if input_layer exists
        existing_refs = set()
        if input_layer:
            existing_refs = set(feat['NATIONALCADASTRALREFERENCE'] for feat in input_layer.getFeatures())
            feedback.pushInfo(f"Riferimenti catastali esistenti: {len(existing_refs)}")
        
        features_added = 0
        last_geometry = None  # Per tracciare l'ultima geometria
        
        for feat in features:
            # Ottieni il riferimento catastale
            ref_catastale = feat['NATIONALCADASTRALREFERENCE']
            
            # Skip if already exists
            if ref_catastale in existing_refs:
                feedback.pushInfo(f"Particella {ref_catastale} già presente nel layer")
                continue
            
            new_feat = QgsFeature()
            new_feat.setGeometry(feat.geometry())
            
            # Imposta gli attributi
            # Trasforma la geometria per il calcolo dell'area
            geom = feat.geometry()
            if geom:
                # Crea il sistema di riferimento di origine e destinazione
                source_crs = QgsCoordinateReferenceSystem('EPSG:6706')
                dest_crs = QgsCoordinateReferenceSystem('EPSG:3045')
                
                # Crea il trasformatore di coordinate
                xform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
                
                # Crea una copia della geometria e la trasforma
                geom_transformed = QgsGeometry(geom)
                geom_transformed.transform(xform)
                
                # Calcola l'area nella proiezione corretta
                area = geom_transformed.area()
            else:
                area = 0
                
            attributes = [
                ref_catastale,
                ref_catastale[:4],
                ref_catastale[4:5],
                ref_catastale[5:9],
                ref_catastale.split('.')[-1],
                area  # Area in metri quadri nel sistema EPSG:3045
            ]
            
            new_feat.setAttributes(attributes)
            sink.addFeature(new_feat)
            features_added += 1
            existing_refs.add(ref_catastale)  # Add to existing refs to prevent duplicates
            last_geometry = feat.geometry()  # Salva l'ultima geometria
            self.last_feature_id = new_feat.id()  # Salva l'ID dell'ultima feature
        
        feedback.pushInfo(f"Aggiunte {features_added} nuove particelle")
        
        # Restituisci sia il successo che l'ultima geometria
        return True, last_geometry

    def postProcessAlgorithm(self, context, feedback):
        """
        Gestisce lo zoom all'ultima particella inserita dopo l'esecuzione dell'algoritmo.
        """
        if not hasattr(self, 'last_geometry') or not self.last_geometry:
            return {}
            
        try:
            from qgis.utils import iface
            if iface and iface.mapCanvas():
                # Calcola il bounding box con margine
                rect = self.last_geometry.boundingBox()
                
                # Calcola un margine proporzionale alla dimensione della particella
                width = rect.width()
                height = rect.height()
                margin = max(width, height) * 0.2  # 20% di margine
                
                # Espandi il rettangolo in modo uniforme
                rect.setXMinimum(rect.xMinimum() - margin)
                rect.setXMaximum(rect.xMaximum() + margin)
                rect.setYMinimum(rect.yMinimum() - margin)
                rect.setYMaximum(rect.yMaximum() + margin)
                
                # Imposta l'estensione e forza l'aggiornamento
                iface.mapCanvas().setExtent(rect)
                iface.mapCanvas().refresh()
                
                # Evidenzia temporaneamente la particella
                iface.mapCanvas().flashFeatureIds(
                    context.getMapLayer(self.last_layer_id),
                    [self.last_feature_id] if hasattr(self, 'last_feature_id') else []
                )
                
                feedback.pushInfo("Zoom eseguito con successo sull'ultima particella")
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
                # Ottieni il bbox della geometria
                rect = self.geometry.boundingBox()
                # Espandi leggermente il bbox
                rect.scale(1.2)
                # Imposta l'extent della mappa
                iface.mapCanvas().setExtent(rect)
                iface.mapCanvas().refresh()
        except Exception as e:
            feedback.reportError(f"Errore durante lo zoom: {str(e)}")