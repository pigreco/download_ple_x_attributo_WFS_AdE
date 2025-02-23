# -*- coding: utf-8 -*-
"""
/***************************************************************************
 WMF Catasto Agenzia delle Entrate CC BY 4.0
                              -------------------
        copyright            : (C) 2025 by Totò Fiandaca
        email                : pigrecoinfinito@gmail.com
 ***************************************************************************/
"""

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                      QgsFeatureSink,
                      QgsProcessingException,
                      QgsProcessingAlgorithm,
                      QgsProcessingParameterString,
                      QgsProcessingParameterFeatureSink,
                      QgsProcessingParameterVectorLayer,
                      QgsProcessingParameterCrs,
                      QgsVectorLayer,
                      QgsField,
                      QgsFields,
                      QgsFeature,
                      QgsGeometry,
                      QgsPointXY,
                      QgsWkbTypes,
                      QgsExpression,
                      QgsExpressionContext,
                      QgsCoordinateReferenceSystem,
                      QgsFeatureRequest,
                      QgsProject)
from qgis.utils import iface
import duckdb
import urllib.request
import json

class CatastaleSearchAlgorithm(QgsProcessingAlgorithm):
    """
    Algoritmo per la ricerca di particelle catastali tramite il servizio WFS
    dell'Agenzia delle Entrate.
    """
    
    # Definizione delle costanti per i parametri
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    COMUNE = 'COMUNE'
    FOGLIO = 'FOGLIO'
    PARTICELLA = 'PARTICELLA'
    CRS = 'CRS'
    
    def __init__(self):
        super().__init__()
        self.wfs_url = 'https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php'
        self.parquet_index = 'https://raw.githubusercontent.com/ondata/dati_catastali/main/S_0000_ITALIA/anagrafica/index.parquet'
        self.parquet_base = 'https://raw.githubusercontent.com/ondata/dati_catastali/main/S_0000_ITALIA/anagrafica/'

    def tr(self, string):
        """
        Returns a translatable string with the self.tr() function.
        """
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return CatastaleSearchAlgorithm()

    def name(self):
        return 'ricercaparticelle'

    def displayName(self):
        return self.tr('Ricerca Particelle Catastali')

    def group(self):
        return self.tr('Catasto')

    def groupId(self):
        return 'catasto'

    def shortHelpString(self):
        return self.tr("""
        Ricerca particelle catastali utilizzando il servizio WFS dell'Agenzia delle Entrate.
        
        Parametri:
        - Layer esistente: (opzionale) layer a cui aggiungere le nuove particelle
        - Codice comune: codice Belfiore del comune (es. M011)
        - Foglio: numero del foglio catastale (es. 0002)
        - Particella: numero della particella (es. 2)
        - Sistema di riferimento: CRS per il layer di output
        
        Output:
        Layer vettoriale contenente le particelle trovate con i relativi attributi
        
        Note:
        - Se viene specificato un layer esistente, le nuove particelle verranno aggiunte ad esso
        - La vista verrà automaticamente centrata sull'ultima particella aggiunta
        """)

    def check_internet_connection(self):
        """
        Verifica la connessione internet tentando di raggiungere un server noto
        """
        try:
            urllib.request.urlopen('https://www.google.com', timeout=3)
            return True
        except:
            return False

    def validate_inputs(self, comune, foglio, particella):
        """
        Valida i parametri di input
        """
        if not comune or len(comune) != 4:
            raise QgsProcessingException(
                self.tr('Il codice comune deve essere di 4 caratteri')
            )
        
        if not foglio.isdigit():
            raise QgsProcessingException(
                self.tr('Il foglio deve contenere solo numeri')
            )
            
        if not particella or not particella.strip():
            raise QgsProcessingException(
                self.tr('La particella non può essere vuota')
            )

    def initAlgorithm(self, config=None):
        """
        Inizializzazione dei parametri dell'algoritmo
        """
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
                self.tr('Layer esistente (opzionale)'),
                [QgsProcessing.TypeVectorPolygon],
                optional=True
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.COMUNE,
                self.tr('Codice comune'),
                defaultValue='M011'
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.FOGLIO,
                self.tr('Foglio'),
                defaultValue='0002'
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.PARTICELLA,
                self.tr('Particella'),
                defaultValue='2'
            )
        )
        
        self.addParameter(
            QgsProcessingParameterCrs(
                self.CRS,
                self.tr('Sistema di riferimento'),
                defaultValue='EPSG:6706'
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Particelle trovate')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """
        Esecuzione dell'algoritmo
        """
        # Verifica connessione internet
        if not self.check_internet_connection():
            raise QgsProcessingException(
                self.tr('Connessione internet non disponibile')
            )

        # Recupera i parametri
        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        comune = self.parameterAsString(parameters, self.COMUNE, context).strip().upper()
        foglio = self.parameterAsString(parameters, self.FOGLIO, context).strip().zfill(4)
        particella = self.parameterAsString(parameters, self.PARTICELLA, context).strip()
        output_crs = self.parameterAsCrs(parameters, self.CRS, context)

        # Valida i parametri
        self.validate_inputs(comune, foglio, particella)

        # Prepara i campi
        fields = QgsFields()
        fields.append(QgsField('NATIONALCADASTRALREFERENCE', QVariant.String))
        fields.append(QgsField('ADMIN', QVariant.String))
        fields.append(QgsField('SEZIONE', QVariant.String))
        fields.append(QgsField('FOGLIO', QVariant.String))
        fields.append(QgsField('PARTICELLA', QVariant.String))
        fields.append(QgsField('AREA', QVariant.Double))

        # Gestione layer di output
        if input_layer is None:
            sink, dest_id = self.parameterAsSink(
                parameters,
                self.OUTPUT,
                context,
                fields,
                QgsWkbTypes.MultiPolygon,
                output_crs
            )
            
            if sink is None:
                raise QgsProcessingException(self.tr('Invalid sink creation'))
        else:
            sink = input_layer
            dest_id = sink.id()

        try:
            # Connessione al database
            con = duckdb.connect()
            
            # Query per il file parquet
            feedback.pushInfo(self.tr('Ricerca file parquet...'))
            query = f"""
            SELECT file 
            FROM '{self.parquet_index}'
            WHERE comune LIKE '{comune}'
            LIMIT 1
            """
            result = con.execute(query).fetchall()
            
            if not result:
                raise QgsProcessingException(
                    self.tr('Nessun file trovato per il comune specificato')
                )
                
            file_name = result[0][0]
            feedback.pushInfo(f'File trovato: {file_name}')
            
            # Query per le coordinate
            url = f'{self.parquet_base}{file_name}'
            query = f"""
            SELECT x, y 
            FROM read_parquet('{url}')
            WHERE comune LIKE '{comune}' 
            AND foglio LIKE '{foglio}' 
            AND particella LIKE '{particella}'
            """
            
            result = con.execute(query).fetchall()
            if not result:
                raise QgsProcessingException(self.tr('Coordinate non trovate'))
                
            x = float(result[0][0]) / 1000000
            y = float(result[0][1]) / 1000000
            feedback.pushInfo(f'Coordinate trovate: X={x}, Y={y}')
            
            # Preparazione WFS Layer
            uri = (f"pagingEnabled='true' "
                   f"preferCoordinatesForWfsT11='false' "
                   f"restrictToRequestBBOX='1' "
                   f"srsname='EPSG:6706' "
                   f"typename='CP:CadastralParcel' "
                   f"url='{self.wfs_url}' "
                   f"version='2.0.0'")
            
            wfs_layer = QgsVectorLayer(uri, "catasto_query", "WFS")
            if not wfs_layer.isValid():
                raise QgsProcessingException(self.tr('WFS layer non valido'))
                
            # Richiesta features
            point = QgsGeometry.fromPointXY(QgsPointXY(x, y))
            request = QgsFeatureRequest().setFilterRect(point.boundingBox())
            features = list(wfs_layer.getFeatures(request))
            
            feature_count = len(features)
            feedback.pushInfo(f'Trovate {feature_count} particelle')
            
            # Gestione features esistenti
            existing_refs = set()
            if input_layer is not None:
                existing_refs = set(feat['NATIONALCADASTRALREFERENCE'] for feat in input_layer.getFeatures())
                sink.startEditing()

            last_added_feature = None
            last_ref_catastale = None

            # Processo le features
            for current, feat in enumerate(features):
                if feedback.isCanceled():
                    break
                    
                ref_catastale = feat['NATIONALCADASTRALREFERENCE']
                
                if ref_catastale in existing_refs:
                    continue
                    
                new_feat = QgsFeature(fields)
                new_feat['NATIONALCADASTRALREFERENCE'] = ref_catastale
                new_feat['ADMIN'] = ref_catastale[:4]
                new_feat['SEZIONE'] = ref_catastale[4:5]
                new_feat['FOGLIO'] = ref_catastale[5:9]
                new_feat['PARTICELLA'] = ref_catastale.split('.')[-1]
                
                # Calcolo area
                geom = feat.geometry()
                new_feat.setGeometry(geom)
                area = QgsExpression("Area(transform(@geometry,'EPSG:6706','EPSG:3035'))")
                context = QgsExpressionContext()
                context.setFeature(new_feat)
                area_value = area.evaluate(context)
                new_feat['AREA'] = area_value
                
                if input_layer is not None:
                    sink.addFeature(new_feat)
                else:
                    sink.addFeature(new_feat, QgsFeatureSink.FastInsert)
                    
                last_added_feature = new_feat
                last_ref_catastale = ref_catastale
                feedback.setProgress(int(current * 100 / feature_count))

            # Commit modifiche
            if input_layer is not None:
                sink.commitChanges()
                sink.updateExtents()
                sink.triggerRepaint()

            # Zoom all'ultima feature
            if last_added_feature:
                canvas = iface.mapCanvas()
                
                try:
                    # Se è un layer esistente, usa quello
                    if input_layer is not None:
                        target_layer = input_layer
                    else:
                        # Altrimenti, aggiungi il nuovo layer al progetto
                        memory_layer = QgsVectorLayer(f"MultiPolygon?crs={output_crs.authid()}", "Particelle trovate", "memory")
                        memory_layer.dataProvider().addAttributes(fields)
                        memory_layer.updateFields()
                        memory_layer.dataProvider().addFeatures([last_added_feature])
                        QgsProject.instance().addMapLayer(memory_layer)
                        target_layer = memory_layer
                    
                    if target_layer.isValid() and last_added_feature.hasGeometry():
                        # Zoom alla feature
                        bbox = last_added_feature.geometry().boundingBox()
                        bbox.scale(1.2)
                        
                        target_layer.removeSelection()
                        target_layer.select(last_added_feature.id())
                        
                        canvas.setDestinationCrs(target_layer.crs())
                        canvas.setExtent(bbox)
                        canvas.refresh()
                        
                        feedback.pushInfo(
                            f"Zoom effettuato alla particella {last_added_feature['PARTICELLA']}"
                        )
                    else:
                        feedback.pushWarning("Impossibile eseguire lo zoom: layer o geometria non validi")
                
                except Exception as e:
                    feedback.pushWarning(f"Errore durante lo zoom: {str(e)}")

        except duckdb.Error as e:
            raise QgsProcessingException(f"Errore DuckDB: {str(e)}")
        except Exception as e:
            raise QgsProcessingException(str(e))
        finally:
            con.close()

        return {self.OUTPUT: dest_id}