from pprint import pprint
import pya
import numpy as np
import sys
import re
import os, json
from pathlib import Path
sys.path.append('./src')
# start setting by using class
from gdsInfoClass import M0,M1,M2,V0,V1,V2,GATE,LISD,GCUT,FIN,ACTIVE,Nselect,Pselect,SDT,WELL,PSUB # Import metal layer information

# default
output_dir = "gds_result"
cells = ["./INV_X1"]

cfg_path = os.environ.get("GDSGEN_CONFIG")
if cfg_path and Path(cfg_path).exists():
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    output_dir = cfg.get("output_dir", output_dir)
    cells = cfg.get("cells", cfg.get("filenames", cells))

Path(output_dir).mkdir(parents=True, exist_ok=True)

for filename in cells:
	cell_name = filename.split("/")[-1]
	# parameter setting
	M0_power_rail_width = 144 # 0.018*4000
	M0_power_rail_to_1st_M0_track = 44 # 0.011*4000
	
	# tracking the log
	new_layout = pya.Layout()
	new_layout.dbu = 0.00025
	
	# layer define for layout (top cell)
	M0_layer = new_layout.layer(M0.layer_number, M0.datatype)
	outline_layer = new_layout.layer(100, 0)
	
	new_cell = new_layout.create_cell(f"{cell_name}")
	print(f"Cell name : {cell_name}")
	# Parse file to find the first encountered row and column length
	column_length = 0
	nets_data = {}
	combined_pmos = {}
	combined_nmos = {}
	ordered_devices = []
	
	order=[]
	
	with open(filename, 'r') as file:
	    for line in file:
	        line = line.strip()
	
	        #---------------------------------------------------------
	        # 1) Collect "PMOS: 2 [...]", "PMOS: 1 [...]", etc.
	        #    Collect "NMOS: 2 [...]", "NMOS: 1 [...]", etc.
	        #---------------------------------------------------------
	        if line.startswith("PMOS:") or line.startswith("NMOS:"):
	            # Example line: "PMOS: 2 ['QN0', 'net1', 'VDD', ...]"
	            m = re.match(r'^(PMOS|NMOS):\s*(\d+)\s*(\[.*\])$', line)
	            if m:
	                device_type = m.group(1)  # "PMOS" or "NMOS"
	                order.insert(0,device_type)
	                height_str = m.group(2)
	                height = int(height_str)
	                array_str = m.group(3)    # The bracketed list as a string
	
	                # Convert bracketed list string to actual Python list
	                device_list = eval(array_str)  # Caution with eval if untrusted
	
	                if device_type == "PMOS":
	                    # Append or create a new list at the given height
	                    if height not in combined_pmos:
	                        combined_pmos[height] = []
	                    combined_pmos[height].append(device_list)
	
	                else:  # device_type == "NMOS"
	                    if height not in combined_nmos:
	                        combined_nmos[height] = []
	                    combined_nmos[height].append(device_list)
	                
	                ordered_devices.append({
	                    "type": device_type,
	                    "height": height,
	                    "devices": device_list
	                })
	
	            continue  # Move to next line
	
	        #---------------------------------------------------------
	        # 2) Parse Net lines:
	        #    - "Net netX: Via positions [], []"
	        #    - "Net netX, H 2, Row 13: [ 0, 0, ... ]"
	        #---------------------------------------------------------
	        if line.startswith("Net "):
	            if "Via positions" in line:
	                m = re.match(r'^Net\s+(\S+):\s*Via positions\s*(\[.*?\])\s*,\s*(\[.*?\])$', line)
	                if m:
	                    net_name = m.group(1)
	                    bracket_single = m.group(2).strip()  # ex) "[(2, 20)]"
	                    bracket_double = m.group(3).strip()  # ex) "[16]"
	
	                    via_single_tuples = re.findall(r'\((\d+)\s*,\s*(\d+)\)', bracket_single)
	                    via_single = [(int(h), int(pos)) for (h, pos) in via_single_tuples]
	                    via_double_nums = re.findall(r'\d+', bracket_double)
	                    via_double = [int(num) for num in via_double_nums]
	
	                    if net_name not in nets_data:
	                        nets_data[net_name] = {}
	                    nets_data[net_name]["via_single"] = via_single
	                    nets_data[net_name]["via_double"] = via_double
	
	            # B) Net row line: "Net net3, H 2, Row 13: [0, 0, 0...]"
	            elif ", H " in line and ", Row " in line:
	                # Use a regex to parse "Net <name>, H <height>, Row <row>: [data]"
	                # Example: "Net net3, H 2, Row 13: [0, 0, 0]"
	                m = re.match(r'^Net\s+(\S+),\s*H\s+(\d+),\s*Row\s+(\d+):\s*\[(.*)\]$', line)
	                if m:
	                    net_name = m.group(1)
	                    net_height = int(m.group(2))
	                    row_num = int(m.group(3))
	                    row_data_str = m.group(4)
	
	                    # Convert the comma-separated row data to a list
	                    row_data = [x.strip() for x in row_data_str.split(',')]
	
	                    if net_height == 2:
	                        row_num -= 10
	
	                    # Initialize net if not present
	                    if net_name not in nets_data:
	                        nets_data[net_name] = {}
	
	                    # Store row data in a sub-dictionary
	                    if 'rows' not in nets_data[net_name]:
	                        nets_data[net_name]['rows'] = {}
	
	                    # Save row_data
	                    nets_data[net_name]['rows'][net_height,row_num] = row_data
	
	                    # Track max column length
	                    if len(row_data) > column_length:
	                        column_length = len(row_data)
	
	            continue  # Move to next line
	cpp = int((column_length+1)/2)
	height = int(len(ordered_devices)/2)
	
	# Draw the outline as a square on layer 100
	if column_length > 0:
	    # Create a box for the outline and add to the new cell
	    outline_box = pya.Box(0, 0, cpp * (GATE.width+GATE.pitch), GATE.length*height)
	    new_cell.shapes(outline_layer).insert(outline_box)
	
	## Draw layers for canvas
	GATE.draw_layer_rects(new_cell, new_layout, start_x=0, y_offset=0, outline_right=outline_box.right, outline_top=outline_box.top)
	GCUT.draw_layer_rects(new_cell, new_layout, start_x=0, y_offset=0, outline_right=outline_box.right, outline_top=outline_box.top)
	LISD.draw_layer_rects(new_cell, new_layout, start_x=90, y_offset=52, outline_right=outline_box.right, outline_top=outline_box.top)
	SDT.draw_layer_rects(new_cell, new_layout, start_x=90, y_offset=52, outline_right=outline_box.right, outline_top=outline_box.top)
	#LISD.draw_layer_rects(new_cell, new_layout, start_x=90, y_offset=296, outline_right=outline_box.right, outline_top=outline_box.top)
	FIN.draw_layer_rects(new_cell, new_layout, start_x=0, y_offset=-FIN.width/2, outline_right=outline_box.right, outline_top=outline_box.top)
	ACTIVE.draw_layer_rects(new_cell, new_layout, start_x=0, y_offset=52, outline_right=outline_box.right, outline_top=outline_box.top)
	Nselect.draw_layer_rects(new_cell, new_layout, start_x=0, y_offset=0, outline_right=outline_box.right, outline_top=outline_box.top, order=order)
	Pselect.draw_layer_rects(new_cell, new_layout, start_x=0, y_offset=0, outline_right=outline_box.right, outline_top=outline_box.top, order=order)
	WELL.draw_layer_rects(new_cell, new_layout, start_x=0, y_offset=0, outline_right=outline_box.right, outline_top=outline_box.top, order=order)
	M0.horizontal_power_gen(new_cell, new_layout, 0, M0_power_rail_width, outline_box.right, outline_box.top,GATE.length)
	GCUT.horizontal_power_gen(new_cell, new_layout, 0, M0_power_rail_width, outline_box.right, outline_box.top,GATE.length, order,combined_pmos,combined_nmos)
	LISD.horizontal_power_gen(new_cell, new_layout, 0, M0_power_rail_width, outline_box.right, outline_box.top,GATE.length, order,combined_pmos,combined_nmos)
	V0.power_gen(new_cell, new_layout, LISD.width, LISD.pitch, M0_power_rail_width, outline_box.right, outline_box.top,GATE.length, order, combined_pmos, combined_nmos)
	
	## draw routing result
	M0.draw_horizontal(new_cell, new_layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track)
	V1.draw_V1(new_cell, new_layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track)
	V2.draw_V2(new_cell, new_layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track)
	V0.draw_V0(new_cell,new_layout,nets_data,combined_pmos,combined_nmos,M0_power_rail_width,M0_power_rail_to_1st_M0_track)
	M1.draw_M1_custom(new_cell,new_layout,M0_power_rail_width,M0_power_rail_to_1st_M0_track, nets_data)
	M2.draw_horizontal(new_cell, new_layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track)
	
	# merge segments
	M0.merge_layers_or(new_cell,new_layout)
	M1.merge_layers_or(new_cell,new_layout)
	M2.merge_layers_or(new_cell,new_layout)
	GATE.merge_layers_or(new_cell,new_layout)
	LISD.merge_layers_or(new_cell,new_layout)
	GCUT.merge_layers_or(new_cell,new_layout)
	
	# label gen
	M0.create_labels(new_cell,new_layout,nets_data,M0_power_rail_width,M0_power_rail_to_1st_M0_track,10,outline_box.right,order=order)
	
	# extract output
	new_layout.write(f"{output_dir}/{cell_name}.gds")
