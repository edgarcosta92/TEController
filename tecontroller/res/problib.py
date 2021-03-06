"""Module that implements the functions to calculate the congestion
probabilities when activating ECMP in a routers of a network. 
"""
from tecontroller.res import defaultconf as dconf
from scipy.misc import comb, factorial
import itertools as it
import numpy as np
import marshal
import random
import time

# Change version constant
marshal.version = 4

class ProbabiliyCalculator(object):
    def __init__(self, dump_filename=dconf.MarshalFile):
        self.dump_filename = dump_filename
        self.sdict = self.loadSDict()
        self.timer = Timer()

    def loadSDict(self):
        try:
            with open(self.dump_filename, 'rb') as dfile:
                data = dfile.read()
                dictionarydump = marshal.loads(data)
                return dictionarydump
        except:
            with open(self.dump_filename, 'wb') as dfile:
                dictionarydump = {}
                data = marshal.dumps(dictionarydump, 4)
                dfile.write(data)
                return dictionarydump
            
    def dumpSDict(self):
        with open(self.dump_filename, 'wb') as dfile:
            data = marshal.dumps(self.sdict, 4)
            dfile.write(data)
            
    def SNonCongestionProbability(self, m, n, k):
        if (m, n, k) in self.sdict.keys():
            return self.sdict[(m,n,k)]

        if m*k < n:
            return 0.0

        if n <= k:
            return 1.0

        else:
            function = lambda t:self.SNonCongestionProbability(m-1, n-t, k)*(float(comb(n, t))*((1/float(m))**t)*((m-1)/float(m))**(n-t))
            result = sum(map(function, range(0, k+1)))

            if (m, n, k) not in self.sdict.keys():
                self.sdict[(m,n,k)] = result
            
            return result

    def SCongestionProbability(self, m, n, k):
        if (m,n,k) in self.sdict.keys():
            return 1.0 - self.sdict[(m,n,k)]

        else:
            sncp = self.SNonCongestionProbability(m,n,k)
            self.sdict[(m,n,k)] = sncp
            self.dumpSDict()
            return 1.0 - sncp

    def ExactCongestionProbability(self, all_dag, flow_paths, flow_sizes):
        """
        In this case, path_capacities is a list of lists, representing possible flow path/s 
        min available capacities : [[c1, c2], [c2]...]
        and n is a list of flow sizes: [s1, s2, ...]

        Flow to paths bidings are given by the lists indexes.

        Returns congestion probability.
        """
        total_samples = 0
        congestion_samples = 0
        for alloc in it.product(*flow_paths):
            # Add sample to total count
            total_samples += 1
            
            # Create copy of all_dag
            adag_c = all_dag.copy()

            # Iterate alloc. For each path i in alloc:
            for index, path in enumerate(alloc):
                # Flag variable to break iteration 
                congestion_found = False
                
                # Subtract size of flow i in all_dag
                for (x, y) in zip(path[:-1], path[1:]):
                    cap = adag_c[x][y]['capacity']
                    cap -= flow_sizes[index]
                    adag_c[x][y]['capacity'] = cap

                    mincap = adag_c[x][y]['mincap']
                    # Perform check: if at some point, available capacity
                    # < 0: break iteration, go to next alloc                    
                    if cap < mincap:
                        congestion_found = True
                        break
                    
                if congestion_found:
                    congestion_samples += 1
                    break
                
        return congestion_samples/float(total_samples)

    def SampledCongestionProbability(self, m, n, percentage=10, estimate=0):
        """
        In this case, m is a list of paths available capacities : [c1, c2, ...]
        and n is a list of flow sizes: [s1, s2, ...]

        returns congestion probability.
        """
        all_allocs = [t for p in it.combinations_with_replacement(range(len(m)), len(n)) for t in it.permutations(p)]
        final_allocs = []
        action = [final_allocs.append(a) for a in all_allocs if a not in final_allocs]

        n_samples = len(final_allocs)

        available_sizes = np.asarray(m)

        laps = 1
        if estimate != 0:
            laps = estimate

        probs = []
        for lap in range(laps):
            # Take percentage % of samples only
            portion_samples = n_samples/percentage
        
            # Choose uniformly at random indexes within final_allocs
            indices = sorted(random.sample(xrange(n_samples), portion_samples)) 
            
            # Filter only those indexes from finall_allocs
            sampled_allocs = [final_allocs[i] for i in indices]

            total_samples = len(sampled_allocs)
            congested_samples = 0
        
            for alloc in sampled_allocs:
                required_sizes = np.zeros(len(m))
                for i, a in enumerate(alloc):
                    required_sizes[a] += n[i]

                balance = available_sizes - required_sizes
                congestion = any(filter(lambda x: True if x < 0 else False, balance))
                if congestion:
                    congested_samples += 1
                    
            probs.append(congested_samples/float(total_samples))
            
        if not estimate:
            return (probs[0], None) 

        else:
            probs = np.asarray(probs)
            return (probs.mean(), probs.std())
        
    def getPathProbability(self, dag, path):
        """Given a DAG and a path defined as a succession of nodes in the
        DAG, it returns the probability of a single flow to be allocated
        in that path.
        """
        probability = 1
        for node in path[:-1]:
            children = len(dag[node])
            probability *= 1/float(children)
        return probability

    def flowCongestionProbability(self, dag, ingress_router, egress_router, flow_size):
        """We assume DAG edges incorporate the available capacities:
        dag[x][y] is a dictionary with a 'capacity' key.
        """
        # Calculate all possible paths
        all_paths = getAllPathsLimDAG(dag, ingress_router, egress_router, 0)

        # Get those who own links that create congestion
        paths_congestion = [path for path in all_paths if getMinCapacity(dag, path) < flow_size]

        congestion_probability = 0
        # Iterate those paths
        for path in paths_congestion:
            # Compute the probability of each of these paths to happen
            # Add it to the total congestion probability (union)
            congestion_probability += self.getPathProbability(dag, path)
            
        return congestion_probability


class Timer(object):
    def __init__(self, verbose=False):
        self.verbose = verbose
        
    def __enter__(self):
        self.start = time.time()
        return self
    
    def __exit__(self, *args):
        self.end = time.time()
        self.secs = self.end - self.start
        self.msecs = self.secs * 1000  # millisecs
        if self.verbose:
            print 'elapsed time: %f ms' % self.msecs
            
    
# Useful functions not included in the object #################

def getAllPathsLimDAG(dag, start, end, k, path=[]):
    """Recursive function that finds all paths from start node to end node
    with maximum length of k.
    
    If the function is called with k=0, returns all existing
    loopless paths between start and end nodes.
    
    :param dag: nx.DiGraph representing the current paths towards
    a certain destination.
    
    :param start, end: string representing the ip address of the
    star and end routers (or nodes) (i.e:
    10.0.0.3).
    
    :param k: specified maximum path length (here means hops,
    since the dags do not have weights).
    
    """
    # Accumulate nodes in path
    path = path + [start]
    
    if start == end:
        # Arrived to the end. Go back returning everything
        return [path]
        
    if not start in dag:
        return []

    paths = []
    for node in dag[start]:
        if node not in path: # Ommiting loops here
            if k == 0:
                # If we do not want any length limit
                newpaths = getAllPathsLimDAG(dag, node, end, k, path=path)
                for newpath in newpaths:
                    paths.append(newpath)
            elif len(path) < k+1:
                newpaths = getAllPathsLimDAG(dag, node, end, k, path=path)
                for newpath in newpaths:
                    paths.append(newpath)
    return paths

def getMinCapacity(dag, path):
    """
    Iterate dag through edges of the path and return the 
    minimum observed available capacity
    """
    caps = [dag[u][v]['capacity'] for u, v in zip(path[:-1], path[1:])]
    return min(caps)

