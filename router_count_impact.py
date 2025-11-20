#!/usr/bin/env python3


import logging
import resource
import contextlib
import os
import re
import sys
import random
from datetime import datetime
import time

from otns.cli import OTNS
from otns.cli.errors import OTNSExitedError

PROJECTNAME = "electro/single"

PROGRESS_LOG = f".progress-{PROJECTNAME.replace('/', '_')}.log"
MAIN_START = 1          # const used for router upgrade threshold if not stated differently in PROGRESS_LOG
MAIN_STOP = 32

# pre KPI measurement parameters
CONVERGE_TIME = 600     # time used to simulate network before KPI measurements starts

# parameter for KPI measurement function
DURATION:float = 3600   # duration of simulation (seconds)
COAP_EVERY:float = 1    # (seconds) simulate for XX until new message
PAYLOAD:int = 100        # (B) how big payload should be packeet into COAP msg !!IF PAYLOAD = 0 NO COAP WILL BE SEND
REPEAT_KPI:int = 20     # how many time should KPI measure should be repeated
NUM_OF_MESSAGES:int = 1 # how many messages should node send to in COAP_EVERY duration (2+ ==> burst)


destination_id = 1

###### TOPOLOGY parameters ######
TOPO_COLUMNS = 5
TOPO_ROWS = 6
topo_gap = 100
TOPO_OFFSET_X = 100
TOPO_OFFSET_Y = 200
add_delay = 5
#################################

###### ROUTERS parameters ######
rtr_up_thr = 1
rtr_up_dwn_gap = 10  ################################
rtr_dwn_thr = rtr_up_thr + rtr_up_dwn_gap
rtr_sel_jitter:int = 1
#################################

class rtr_stats:
    rtrupgrthr = 0
    rtrdwngrthr = 0
    rtrseljitter = 0

class sim_stats:
    num_of_leaders_start = 0
    num_of_leaders_stop = 0
    num_of_routers_start = 0
    num_of_routers_stop = 0

def create_topo(ns, start_x, start_y, columns: int, rows: int, gap: int,
                    routerupgradethreshold: int = 16,
                    routerdowngradethreshold: int = 23 ):
    for row in range(rows):
        for column in range(columns): 
            x_position = start_x + column * gap
            y_position = start_y + row * gap

            cmd_selection_jitter = f"routerselectionjitter {rtr_sel_jitter}"
            cmd_upgrade_threshold = f"routerupgradethreshold {routerupgradethreshold}" 
            cmd_downgrade_threshold = f"routerdowngradethreshold {routerdowngradethreshold}"
               
            new_node = ns.add("router", x=x_position, y=y_position)
            ns.node_cmd(new_node, cmd_selection_jitter)
            ns.node_cmd(new_node, cmd_upgrade_threshold)
            ns.node_cmd(new_node, cmd_downgrade_threshold)


def kpi_random_coap(ns,
                    duration: float = 10,
                    repeat: int = 3,
                    datasize: int = 0,
                    step: float = 1,
                    num_of_messages: int = 1
                    ):
    """
    function that for duration of time sends randomly COAP messages to node 1.
    Sending node is randomly selected from all possible nodes

    :param duration: how long whole simulation will run. used in whhile cycle
    :param repeat: how many times to repeat simulation (how many times repeat while cycle), default 1
    :param datasize: size of payload of COAP message that is sent from src to dst node in bytes, default 180 
    :param step: defines time different between sendting new COAP message, used to set duration in go function OTNS.py ,
                 default 1 second
    :param num_of_messages: define number of reptetition of send command, effectively sending one or more messages (burst transmission)
    """

    # get list of id's 
    id_list = get_node_id_list(ns)
    get_node_config(ns, 5)

    print("running KPI measurement for " +str(duration) +" seconds; "
          + "No of runs: " + str(repeat) + "; COAP datasize [bytes]: " +str(datasize) 
          + "; time between new message: " + str(step) + "; num_of_messages: " + str(num_of_messages))

    # repeat simulation for defined number of times
    for run in range(1, (repeat+1)):
        # print("  run: "+ str(run) + " of " +str(repeat))
        print_progressbar(run, repeat)

        # define start time
        start_time = ns.time
        actual_time = ns.time
        
        sim_stats.num_of_routers_start = get_num_of_devices(ns, dev_state="router")
        sim_stats.num_of_leaders_start = get_num_of_devices(ns, dev_state="leader")
        ns.kpi_start()
        
        while (actual_time - start_time) < duration:

            #If datasize/PAYLOAD is bigger then 0 message will betransmitted else nothing
            if(datasize > 0):
                # randomly select node and send message
                random_id = random.choice(id_list)
                message_cmd = f'send coap {random_id} {destination_id} datasize {datasize}'
                for i in range (1, (num_of_messages+1)):
                    ns.cmd(message_cmd)
                ns.go(duration = step)
            else:
                ns.go(duration = duration)
            
            actual_time = ns.time
        
        ns.go(duration = add_delay)
        ns.kpi_stop()

        sim_stats.num_of_routers_stop = get_num_of_devices(ns, dev_state="router")
        sim_stats.num_of_leaders_stop = get_num_of_devices(ns, dev_state="leader")

        # save KPI file
        parent_folder = f"./xaver/{PROJECTNAME}/gap_{rtr_up_dwn_gap:02}/{datasize:03}B"
        foldername = f'RupThr_{rtr_stats.rtrupgrthr:02}-RdwnThr_{rtr_stats.rtrdwngrthr:02}-{datasize:03}B'
        filename = f'kpi-{run:03}'
        save_kpi_to_folder(ns, parent_folder = parent_folder,
                            folder = foldername,
                            name = filename)   

def save_kpi_to_folder(ns, parent_folder, folder, name):
        
    folder_path = f'{parent_folder}/{folder}'
    print("saving KPI file: " + folder_path + "/" + name + ".json", end=" ")
    
    os.makedirs(parent_folder, exist_ok=True)
    os.makedirs(folder_path, exist_ok=True)
    
    ns.kpi_save(f'{folder_path}/{name}.json')
    # save medatadata
    log_metadata_to_file(foldername = folder_path, run = name)

def log_metadata_to_file(foldername, run:str):
    file_path = f'{foldername}/num_of_actual_routers.log'

    if os.path.exists(file_path):
        # append mode ('a')
        mode = 'a'
    else:
        # write mode ('w') to overwrite
        mode = 'w'
    
    with open(file_path, mode) as file:
        # Write the log entry
        sum_of_routers_start = sim_stats.num_of_leaders_start + sim_stats.num_of_routers_start    #leaders+routers at start
        sum_of_routers_stop = sim_stats.num_of_leaders_stop + sim_stats.num_of_routers_stop     #leaders+routers at stop
        
        log = f"{run}- "
        log = log + f"start: {sum_of_routers_start:02}_(L-{sim_stats.num_of_leaders_start},R-{sim_stats.num_of_routers_start})---"
        log = log + f"stop: {sum_of_routers_stop:02}_(L-{sim_stats.num_of_leaders_stop},R-{sim_stats.num_of_routers_stop})"
        
        file.write(f"{log} \n")

def get_node_id_list(ns):
    """
    returns array of all node ID's in simulation
    
    """
    nodes = ns.nodes()
    id_list = []
    for id in nodes:
        id_list.append(id)  

    return id_list

def get_num_of_devices(ns, dev_state:str):
    nodes_stats = ns.cmd("nodes")
    count = sum(1 for entry in nodes_stats if f'state={dev_state}' in entry)
    return count 

def get_node_config(ns, id):
    tmp_rtr_dwn_thr = ns.node_cmd(nodeid=id, cmd="routerdowngradethreshold")
    tmp_rtr_up_thr = ns.node_cmd(nodeid=id, cmd="routerupgradethreshold")
    tmp_rtr_sel_jitt = ns.node_cmd(nodeid=id, cmd="routerselectionjitter")

    rtr_stats.rtrdwngrthr = int(tmp_rtr_dwn_thr[0])
    rtr_stats.rtrupgrthr = int(tmp_rtr_up_thr[0])
    rtr_stats.rtrseljitter = int(tmp_rtr_sel_jitt[0])

def log_progress(start, stop, success:bool = False, msg:str = ""):
    date = datetime.now()

    with open(PROGRESS_LOG, "a") as log_file:
        if(not success):
            progress = f"  Simulating MAIN cycle={start} and stop={stop}, rtr_up_down_gap={rtr_up_dwn_gap} \n"

            print(f"saving progress to logfile {PROGRESS_LOG}")
            log_file.write(progress)
            log_file.write(f"___{msg}")
        else:
            log_file.write(f"{date} Simulation finished succesfully \n")
            log_file.write("-" * 50 + "\n")
            print(f"finished, writing to logfile {PROGRESS_LOG}")

def print_progressbar(current, max):
    full_block = "\u2588"
    progress = full_block * (current)
    stop = "." * (max-current)
    # Print the progress bar with carriage return to overwrite the same line
    print(f"\r   progress {current:02} of {max}: [{progress}{stop}] ", end="")

def del_file(file:str):
    if os.path.exists(file):
        os.remove(file)
        print(f"DELETING {file}")
    
def get_sim_params(file:str = PROGRESS_LOG):
    log_file = file
    last_start = None
    last_rtr_up_dwn_gap = None
    last_line = None
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            for line in f:
                start_value = re.search(r"cycle=(\d+)", line)
                gap_value = re.search(r"rtr_up_down_gap=(\d+)", line)
                last_line = line
                if start_value:
                    last_start = int(start_value.group(1))
                    last_rtr_up_dwn_gap = int(gap_value.group(1))
    if (last_line == "-" * 50 + "\n"):
        print("last line got success string ---- returning MAIN_START ")
        return MAIN_START                
    else:
        print(f"last run in found in {PROGRESS_LOG} = cycle {last_start} and rtr_up_down_gap {last_rtr_up_dwn_gap}")  
        return last_start if last_start is not None else MAIN_START
    

def main(start:int, stop:int = MAIN_STOP):
    
    for i in range (start, stop):
        rtr_up_thr = i
        rtr_dwn_thr = rtr_up_thr + rtr_up_dwn_gap
        
        log_msg = f"Running sim with ROUTER_UP_THR: {rtr_up_thr:02}  ROUTER_DWN_THR: {rtr_dwn_thr:02} Payload[B]: {PAYLOAD}"
        log_progress(start = rtr_up_thr, stop = stop, msg = log_msg)
        print(log_msg)

        ns = OTNS(otns_args=['-seed', '1'])
        ns.radiomodel = 'MutualInterference'
        
        # ns.web('main')

        # create Border Router
        border_router = ns.add("br", x = int((TOPO_OFFSET_X + TOPO_COLUMNS * topo_gap) / 2) , y=50)
        cmd_upgrade_threshold = f"routerupgradethreshold {rtr_up_thr}" 
        cmd_downgrade_threshold = f"routerdowngradethreshold {rtr_dwn_thr}"
        ns.node_cmd(border_router, cmd_upgrade_threshold)
        ns.node_cmd(border_router, cmd_downgrade_threshold)
        ns.go(duration = add_delay)

        create_topo(ns, start_x = TOPO_OFFSET_X, start_y = TOPO_OFFSET_Y,
                        columns = TOPO_COLUMNS, rows = TOPO_ROWS, gap = topo_gap,
                        routerupgradethreshold = rtr_up_thr,
                        routerdowngradethreshold = rtr_dwn_thr)

        ns.go(duration=CONVERGE_TIME, speed=1000)   # simulate network before KPI measure. For convergence
        # ns.interactive_cli()
        
        kpi_random_coap(ns, repeat = REPEAT_KPI,
                         duration = DURATION,
                         step = COAP_EVERY,
                         datasize = PAYLOAD,
                         num_of_messages = NUM_OF_MESSAGES
                        )
        
        ns.delete_all()
        ns.close()

        parent_folder = f'./xaver/{PROJECTNAME}/gap_{rtr_up_dwn_gap:02}/{PAYLOAD:03}B'
        foldername = f'RupThr_{rtr_stats.rtrupgrthr:02}-RdwnThr_{rtr_stats.rtrdwngrthr:02}-{PAYLOAD:03}B'
        save_folder = f'{parent_folder}/{foldername}'
        filename = f'packet_capture.pcap'
        print(f'\n saving pcap file: {save_folder}/{filename}')
        ns.save_pcap(f'{save_folder}', f'{filename}')

        print("\n taking quick nap after RUN ")
        time.sleep(10)

    log_progress(start=rtr_up_thr, stop=MAIN_STOP, success = True)    

if __name__ == '__main__':
    try:
        main(start = get_sim_params())

    except OTNSExitedError as ex:
        if ex.exit_code != 0:
            raise
