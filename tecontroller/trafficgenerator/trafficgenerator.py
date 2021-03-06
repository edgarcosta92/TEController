#!/usr/bin/python

"""This module defines a traffic generator script to be executed in
the Traffic Generator host in the mininet network.

Essentially, reads from a flow definition file and schedules the
traffic.

When a new flow must be created: 

 - Sends commands to corresponding hosts to start exchanging data using
  iperf.

 - Informs the LBController through a JSON interface

After scheduling all flows defined in the file, it opens a JSON-flesk
server to wait for further commands.
"""

from fibbingnode.misc.mininetlib.ipnet import TopologyDB
from fibbingnode.misc.mininetlib import get_logger

from tecontroller.res.flow import Flow, Base
from tecontroller.res import defaultconf as dconf
from tecontroller.res.dbhandler import DatabaseHandler

from threading import Thread 
import time
import requests
import sched
import json
import copy
import signal, sys, traceback
import ipaddress
import sys

import flask
app = flask.Flask(__name__)

# logger to log to the mininet cli
log = get_logger()

class TrafficGenerator(Base):
    """Object that creates a Traffic Generator in the network.
    """
    def __init__(self, *args, **kwargs):
        super(TrafficGenerator, self).__init__(*args, **kwargs)
        
        self.scheduler = sched.scheduler(time.time, time.sleep)
        self.db = DatabaseHandler()
        self.thread_handlers = []
                
        #IP of the Load Balancer Controller host.
        try:
            self._lbc_ip = ipaddress.ip_interface(self.db.getIpFromHostName(dconf.LBC_Hostname)).ip.compressed
        except:
            log.info("WARNING: Load balancer controller could not be found in the network\n")
            self._lbc_ip = None

    def _signal_handler(self, signal, frame):
        """
        Terminates trafficgenerator thread gracefully.
        """
        log.info("Signal caught... shuting down!\n")

        # collect all open _createFlow threads
        for t in self.thread_handlers:
            #t.join()
            log.info("_createFlow thread terminated\n")
            
        # exit
        sys.exit(0)
        
            
    def informLBController(self, flow):
        """Part of the code that deals with the JSON interface to inform to
        LBController a new flow created in the network.
        """
        url = "http://%s:%s/newflowstarted" %(self._lbc_ip, dconf.LBC_JsonPort)
        log.info('\t Informing LBController\n')
        log.info('\t   * Flow: %s\n'%self.toLogFlowNames(flow))
        log.info('\t   * Url: %s\n'%url)
        try:
            requests.post(url, json = flow.toJSON())
        except Exception:
            log.info("ERROR: LBC could not be informed!\n")
            log.info("LOG: Exception in user code:\n")
            log.info('-'*60+'\n')
            log.info(traceback.print_exc())
            log.info('-'*60+'\n')            

    def toLogFlowNames(self, flow):
        a = "(%s -> %s): %s, t_o: %s, duration: %s" 
        return a%(self.db.getNameFromIP(flow.src.compressed),
                  self.db.getNameFromIP(flow.dst.compressed),
                  flow.setSizeToStr(flow.size),
                  flow.setTimeToStr(flow.start_time),
                  flow.setTimeToStr(flow.duration))

    def createFlow(self, flow):
        """Calls _createFlow in a different Thread (for efficiency)
        """
        # Start thread that will send the Flask request
        t = Thread(target=self._createFlow, name='_createFlow', args=(flow,)).start()
        # Append thread handler to list
        self.thread_handlers.append(t)

        
    def _createFlow(self, flow):
        """Creates the corresponding iperf command to actually install the
        given flow in the network.  This function has to call
        self.informLBController!
        """
        # Sleep after it is your time to start
        time.sleep(flow['start_time'])

        # Call to informLBController if it is active
        if self._lbc_ip:
            self.informLBController(flow)
            #time.sleep(0.2)
            
        # Create new flow with hosts ip's instead of interfaces
        # Iperf only understands ip's
        flow2 = Flow(src = flow['src'].ip.compressed,
                     dst = flow['dst'].ip.compressed,
                     sport = flow['sport'],
                     dport = flow['dport'],
                     size = flow['size'],
                     start_time = flow['start_time'],
                     duration = flow['duration'])
        
        url = "http://%s:%s/startflow" %(flow2['src'], dconf.Hosts_JsonPort)

        t = time.strftime("%H:%M:%S", time.gmtime())
        log.info('%s - Starting Flow\n'%t) 
        log.info('\t Sending request to host %s\n'%str(flow['src']))
        log.info('\t   * Flow: %s\n'%self.toLogFlowNames(flow))
        log.info('\t   * Url: %s\n'%url)

        # Send request to host to start new iperf client session
        try:
            requests.post(url, json = flow2.toJSON())
        except Exception:
            log.info("ERROR: Request could not be sent to Host!\n")
            log.info("LOG: Exception in user code:\n")
            log.info('-'*60+'\n')
            log.info(traceback.print_exc())
            log.info('-'*60+'\n')            

    def stopFlow(self, flow):
        """Instructs host to stop iperf client session (flow).

        """
        flow2 = Flow(src = flow['src'].ip.compressed,
                     dst = flow['dst'].ip.compressed,
                     sport = flow['sport'],
                     dport = flow['dport'],
                     size = flow['size'],
                     start_time = flow['start_time'],
                     duration = flow['duration'])
        
        url = "http://%s:%s/stopflow" %(flow2['src'], dconf.Hosts_JsonPort)

        t = time.strftime("%H:%M:%S", time.gmtime())
        log.info('%s - Stopping Flow\n'%t) 
        log.info('\t Sending request to host to stop flow %s\n'%str(flow['src']))
        log.info('\t   * Flow: %s\n'%self.toLogFlowNames(flow))
        log.info('\t   * Url: %s\n'%url)

        # Send request to host to start new iperf client session
        try:
            requests.post(url, json = flow2.toJSON())
        except Exception:
            log.info("ERROR: Stop flow request could not be sent to Host!\n")
            
            
    def createRandomFlow(self):
        """Creates a random flow in the network
        """
        pass

    def scheduleRandomFlows(self, ex_time = 60, max_size = "40M"):
        """Creates a random schedule of random flows in the network. This will
        be useful later to evaluate the performance of the
        LBController.
        """
        pass

    def scheduleFileFlows(self, flowfile):
        """Schedules the flows specified in the flowfile
        """
        f = open(flowfile, 'r')
        flows = f.readlines()
        if flows:
            for flowline in flows:
                flowline = flowline.replace(' ','').replace('\n','')
                if flowline != '' and flowline[0] != '#':
                    try:
                        [s, d, sp, dp, size, s_t, dur] = flowline.strip('\n').split(',')
                        # Get hosts IPs
                        src_iface = self.db.getIpFromHostName(s)
                        dst_iface = self.db.getIpFromHostName(d)

                    except Exception:
                        log.info("EP, SOMETHING HAPPENS HERE\n")
                        src_iface = None
                        dst_iface = None
                        
                    if src_iface != None and dst_iface != None:
                        flow = Flow(src = src_iface,
                                    dst = dst_iface,
                                    sport = sp,
                                    dport = dp,
                                    size = size,
                                    start_time = s_t,
                                    duration = dur)
                        #Schedule flow creation
                        self.scheduler.enter(0, 1, self.createFlow, ([flow]))
                    else:
                        log.info("ERROR! Hosts %s and/or %s do not exist in the network!\n"%(s, d))                       
                        
            # Make the scheduler run after file has been parsed
            self.scheduler.run()
        else:
            log.info("\t No flows to schedule in file\n")                
                        
def create_app(appl, traffic_generator):
    appl.config['TG'] = traffic_generator
    return appl

@app.route("/startflow", methods = ['POST'])
def OrchestrateStartFlow():
    """This function will be running in each of the hosts in our
    network. It essentially waits for commands from the
    TrafficGenerator in the Json-Rest interface and creates a
    subprocess for each corresponding iperf client sessions to other
    hosts.
    """
    # Fetch json data
    flow_tmp = flask.request.json
    
    # Fetch the TG Object
    tg = app.config['TG']

    # Create flow from json data.
    # Beware that hosts in flowfile are given by hostnames: s1,d2, etc.
    src = tg.db.getIpFromHostName(flow_tmp['src'])
    dst = tg.db.getIpFromHostName(flow_tmp['dst'])
    
    flow = Flow(src, dst, flow_tmp['sport'], flow_tmp['dport'],
                flow_tmp['size'], flow_tmp['start_time'], flow_tmp['duration'])

    try:
        tg.createFlow(flow)
    except Exception, err:
        log.info("ERROR: could not create flow:\n")
        log.info(" * %s\n"%flow)
        log.info(traceback.format_exc())


@app.route("/stopflow", methods = ['POST'])
def OrchestrateStopFlow():
    """This function will be running in each of the hosts in our
    network. It essentially waits for commands from the
    TrafficGenerator in the Json-Rest interface and creates a
    subprocess for each corresponding iperf client sessions to other
    hosts.
    """
    # Fetch json data
    flow_tmp = flask.request.json
    
    # Fetch the TG Object
    tg = app.config['TG']

    # Create flow from json data.
    # Beware that hosts in flowfile are given by hostnames: s1,d2, etc.
    src = tg.db.getIpFromHostName(flow_tmp['src'])
    dst = tg.db.getIpFromHostName(flow_tmp['dst'])
    
    flow = Flow(src, dst, flow_tmp['sport'], flow_tmp['dport'],
                flow_tmp['size'], flow_tmp['start_time'], flow_tmp['duration'])

    try:
        tg.stopFlow(flow)
    except Exception, err:
        log.info("ERROR: could not stop flow:\n")
        log.info(" * %s\n"%flow)

        
if __name__ == '__main__':

    # Wait for the network to be created correcly: IP's assigned, etc.
    time.sleep(dconf.TG_InitialWaitingTime)

    # Start the traffic generator object
    tg = TrafficGenerator()

    # Set the signal handler function
    signal.signal(signal.SIGTERM, tg._signal_handler)
    signal.signal(signal.SIGINT, tg._signal_handler)
    
    # Get Traffic Generator hosts's IP.
    MyOwnIp = tg.db.getIpFromHostName(dconf.TG_Hostname).split('/')[0]
    t = time.strftime("%H:%M:%S", time.gmtime())
    log.info("%s - TRAFFIC GENERATOR - HOST %s\n"%(t, MyOwnIp))
    log.info("-"*60+"\n")

    # Schedule flows from file
    # Parse command line
    flowfile = sys.argv[2]
    if flowfile == 'None':
        flowfile = dconf.defaultFlowFile

    t = time.strftime("%H:%M:%S", time.gmtime())
    st = time.time()
    log.info("%s - Scheduling flow file: %s ...\n"%(t, flowfile))

    tg.scheduleFileFlows(flowfile)
    
    t2 = time.strftime("%H:%M:%S", time.gmtime())
    log.info("%s - Scheduled flow file after %.3f seconds\n"%(t2, time.time()-st))

    # Go start the JSON API server and listen for commands
    app = create_app(app, tg)
    app.run(host=MyOwnIp, port=dconf.TG_JsonPort)
