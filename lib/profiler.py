from logger import Logger
import csv
import networkx as nx
import ogr
from qgis.core import *

class Profile():

    def __init__(self, shpLayer, inID, outID=None):
        """
        Profile a network from startID to endID

        If no outID is specified we go and found the outflow point and use that

        :param shpLayer: The QgsVector layer to use
        :param inID:  The ID of the input network segment
        :param outID:  The ID of the output network segment (Optional) Default is none
        """
        # TODO: Could not find because those points are in two different subnetworks. Please fix your network
        # TODO: Could not find because stream flow was a problem. If you reverse your input and output then it works

        log = Logger("Main")

        self.idField = "_FID_"

        # Convert QgsLayer to NX graph
        self.qgsLayertoNX(shpLayer, simplify=True, geom_attrs=False)
        # Find the shortest path between 'in' and 'out'
        self.path_edges = self.nxShortestPath(inID, outID)

        self.attr = []

        log.info('Calculating lengths...')

        cummulativelength = 0
        for edge in self.path_edges:
            # Get the ID for this edge
            attrField = self.G.get_edge_data(*edge)

            attrCalc = {}
            attrCalc['ProfileCalculatedLength'] = attrField['_calc_length_']
            cummulativelength += attrCalc['ProfileCalculatedLength']
            attrCalc['ProfileCummulativeLength'] = cummulativelength

            attrCalc['startLat'] = edge[0][0]
            attrCalc['startLng'] = edge[0][1]

            # Calculate length and cumulative length
            self.attr.append({
                'shpfields': attrField,
                'calculated': attrCalc,
                'edge': edge
            })
        log.info('Pathfinding complete. Found a path with {} segments'.format(len(self.attr)))



    def writeCSV(self, filename, colstr = ""):
        """
        Separate out the writer so we can test without writing files
        :param outdict:
        :param csv:
        :return:
        """
        log = Logger("CSV Writer")
        results = []
        log.info("Writing CSV file")
        if len(self.attr) == 0:
            log.error("WARNING: No rows to write to CSV. Nothing done")
            return

        # Make a subset dictionary
        includedShpCols = []
        if len(colstr) > 0:
            inputDesiredCols = colstr.split(',')
            for col in inputDesiredCols:
                if col not in results[0]:
                    log.error("WARNING: Could not find column '{}' in shapefile".format(col))
                else:
                    includedShpCols.append(col)
        else:
            includedShpCols = self.attr[0]['shpfields'].keys()

        # Now just pull out the columns we need
        for node in self.attr:
            csvDict = {}

            # The ID field is not optional
            csvDict[self.idField] = node['shpfields'][self.idField]

            # Only some of the fields get included
            for key, val in node['shpfields'].iteritems():
                if key in includedShpCols:
                    csvDict[key] = val
            # Everything calculated gets included
            for key, val in node['calculated'].iteritems():
                csvDict[key] = val

            results.append(csvDict)



        with open(filename, 'wb') as filename:
            keys = results[0].keys()

            # pyt the keys in order
            def colSort(a, b):
                # idfield should bubble up
                item = self.attr[0]
                if a == self.idField:
                    return -1
                elif b == self.idField:
                    return 1
                # put shpfields ahead of calc fields
                elif (a in item['shpfields'] and b in item['calculated']):
                    return -1
                elif (a in item['calculated'] and b in item['shpfields']):
                    return 1
                # Sort everything else alphabetically
                elif (a in item['shpfields'] and b in item['shpfields']) or (a in item['calculated'] and b in item['calculated']):
                    if a.lower() > b.lower():
                        return 1
                    elif a.lower() < b.lower():
                        return -1
                    else:
                        return 0
                else:
                    return -1

            keys.sort(colSort)


            writer = csv.DictWriter(filename, keys)
            writer.writeheader()
            writer.writerows(results)
        log.info("Done Writing CSV")


    def nxShortestPath(self, inID, outID=None):
        """
        Find the shortest path between two nodes or just one node and the outflow
        :param G:
        :param inID:
        :param outID:
        :return:
        """
        log = Logger("nxShortestPath")
        path_edges = None
        startNode = self.findnodewithID(inID)

        if not startNode:
            raise Exception("Could not find start ID: {} in network.".format(inID))

        if outID:
            endNode = self.findnodewithID(outID)
            if not endNode:
                raise Exception("Could not find end ID: {} in network.".format(outID))
            # Make a depth-first tree from the first headwater we find
            try:
                shortestpath = nx.shortest_path(self.G, source=startNode[0], target=endNode[1])
                path_edges = zip(shortestpath, shortestpath[1:])
            except Exception, e:
                log.error("Path not found between these two points with id: '{}' and '{}'".format(inID, outID))
                raise e
        else:
            try:
                path_edges = list(nx.dfs_edges(self.G, startNode[0]))
            except Exception, e:
                log.error("Path not found between input point with ID: {} and outflow point".format(inID))

        return path_edges


    def qgsLayertoNX(self, shapelayer, simplify=True, geom_attrs=True):
        """
        THIS IS a re-purposed version of load_shp from nx
        :param shapelayer:
        :param simplify:
        :param geom_attrs:
        :return:
        """
        log = Logger('qgsLayertoNX')

        log.info("parsing shapefile into network...")

        log.info("Shapefile successfully parsed into directed network")

        self.G = nx.DiGraph()

        for f in shapelayer.getFeatures():
            flddata = f.attributes()
            fields = [str(fi.name()) for fi in f.fields()]

            g = f.geometry()
            attributes = dict(zip(fields, flddata))
            # We add the _FID_ manually
            attributes['_FID_'] = f.id()
            attributes['_calc_length_'] = g.length()
            # Note:  Using layer level geometry type
            # TODO: THIS MIGHT NOT WORK
            if g.wkbType() == QgsWKBTypes.Point:
                self.G.add_node(g.asPoint(), attributes)

            elif g.wkbType() in (QgsWKBTypes.LineString, QgsWKBTypes.MultiLineString):
                for edge in self.edges_from_line(g, attributes, simplify, geom_attrs):
                    e1, e2, attr = edge
                    self.G.add_edge(e1, e2)
                    self.G[e1][e2].update(attr)
            else:
                raise ImportError("GeometryType {} not supported".
                                  format(g.wkbType()))



    def edges_from_line(self, geom, attrs, simplify=True, geom_attrs=True):
        """
        This is repurposed from the shape helper here:
        https://github.com/networkx/networkx/blob/master/networkx/readwrite/nx_shp.py
        :return:
        """
        if geom.wkbType() == QgsWKBTypes.LineString:
            pline = geom.asPolyline()
            if simplify:
                edge_attrs = attrs.copy()
                # DEBUGGING
                edge_attrs["Wkt"] = geom.exportToWkt()
                if geom_attrs:
                    edge_attrs["Wkb"] = geom.asWkb()
                    edge_attrs["Wkt"] = geom.exportToWkt()
                    edge_attrs["Json"] = geom.exportToGeoJSON()
                yield (pline[0], pline[-1], edge_attrs)
            else:
                for i in range(0, len(pline) - 1):
                    pt1 = pline[i]
                    pt2 = pline[i + 1]
                    edge_attrs = attrs.copy()
                    if geom_attrs:
                        segment = ogr.Geometry(ogr.wkbLineString)
                        segment.AddPoint_2D(pt1[0], pt1[1])
                        segment.AddPoint_2D(pt2[0], pt2[1])
                        edge_attrs["Wkb"] = segment.asWkb()
                        edge_attrs["Wkt"] = segment.exportToWkt()
                        edge_attrs["Json"] = segment.exportToGeoJSON()
                        del segment
                    yield (pt1, pt2, edge_attrs)

        # TODO: MULTILINESTRING MIGHT NOT WORK
        elif geom.wkbType() == QgsWKBTypes.MultiLineString:
            for i in range(geom.GetGeometryCount()):
                geom_i = geom.GetGeometryRef(i)
                for edge in self.edges_from_line(geom_i, attrs, simplify, geom_attrs):
                    yield edge


    def findnodewithID(self, id):
        """
        One line helper function to find a node with a given ID
        :param id:
        :return:
        """
        Logger("FindWithID")
        for e in self.G.edges_iter():
            data = self.G.get_edge_data(*e)
        return next(iter([e for e in self.G.edges_iter() if self.G.get_edge_data(*e)[self.idField] == id]), None)