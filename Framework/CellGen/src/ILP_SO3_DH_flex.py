import re
import gurobipy as gp
print(gp.__file__)
print(gp.__version__)
from gurobipy import GRB
import time, math
import argparse
from pathlib import Path
from ilp_pnr_function import *

model = gp.Model("transistor_placement")
model.setParam('OutputFlag', 1)  # Suppress Gurobi output
#model.setParam('Presolve', 2)
#model.setParam("Method", 1) # Method=0 default. / Method=1: Primal Simplex. / Method=2: Dual Simplex. / Method=3: Barrier.
#model.setParam("NodeMethod", 2)
#model.setParam("BarIterLimit", 1000) # for method 3
#model.setParam("Crossover", 0) # for method 3
model.setParam('LogFile', 'gurobi.log')
#model.setParam("VarBranch", 2)  # 0: auto, 1: Most Infeasible, 2: Strong Branching

# gurobi output file
_log = None

# connecting
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--cdl", required=True, help="Path to input CDL (e.g., ../cdl/SO3_L1.cdl)")
    p.add_argument("--cell", required=False, help="Cell/Subckt name (e.g., INV_X1)")
    p.add_argument("--subckt", required=False, help="(Deprecated) same as --cell")
    p.add_argument("--dummy-for-ideal", type=int, default=0)
    p.add_argument("--dummy-padding", type=int, default=0)
    p.add_argument("--misalign-col", type=int, default=0)
    # New: DH-only option to choose the multi-height transistor row order
    p.add_argument("--mh-order", choices=["N_FIRST", "P_FIRST"], default="N_FIRST",
                        help="DH row order: N_FIRST->NPPN..., P_FIRST->PNNP...")
    p.add_argument("--out-cell-name", default=None,
                help="(optional) override cell name used for ILP outputs")
    return p.parse_args()

args = parse_args()
cell_name = args.cell or args.subckt
cell_name_for_io = args.out_cell_name or args.cell

if not cell_name:
    raise SystemExit("ERROR: --cell is required (or use --subckt for backward-compat)")

with open(args.cdl, 'r') as f:
    lines = f.readlines()

########################################################## user define
# for placement
unit_fin = 2
subckt_name     = cell_name
dummy_for_ideal = int(args.dummy_for_ideal)
dummy_padding   = int(args.dummy_padding)
dummy_col = int(dummy_for_ideal + dummy_padding)
misalign_col    = int(args.misalign_col)
power_net={'VDD','VSS'}
# for routing
routing_switch = 'on'
bbox = 1 # bounding box for routing
MAX_TRACK = 4 # TRACK DEFINE : 5,4,3,2
upper_rows=[7,5] # [7,6,5,4] m2 4track, [5,4,3] # m2 3track, [9,8,7,6,5] # m2 5track, [3,2] # m2 2track
metal_mar = 'Naive' # DR define : Strict or Naive or Min
via_overlap = 'Naive'
Architecture = '2to3'
zero_offset = 'on'
# for MH
#mh_order = 'N_FIRST' # P_FIRST : PNNP~ or N_FIRST : NPPN~
mh_order = args.mh_order
height = [1, 2] # currently only 2x .. 3x? 4x?
# partition
partition = 'N' # only two way(transistor _1, _2) H : Height partition / LR : Left, Right partition / N : no partition
######################################################################

# Design Settings

if metal_mar =='Naive': M_MAR = 2 # MAR = 2*c (Naive), 3*c (Strict) 1*c (Min)
elif metal_mar =='Strict': M_MAR = 3
elif metal_mar =='Min': M_MAR = 1
if via_overlap == 'Min' : V_OVL = 1
elif via_overlap == 'Naive' : V_OVL = 0
if Architecture == '2to3' : V_PITCH = 4
elif Architecture == '1to1' : V_PITCH = 6
if zero_offset == 'on' : offset = 0
elif zero_offset == 'off' : offset = -V_PITCH/2

# function for saving result
def pr(*args, sep=" ", end="\n"):
    global _log
    if _log is None:
        import atexit
        _log = open(cell_name_for_io, "w", encoding="utf-8", buffering=1)  # line-buffered
        atexit.register(_log.close)

    s = sep.join(str(a) for a in args)
    print(s, end=end)
    _log.write(s + ("" if end is None else end))
    _log.flush()


# cdl analysis

subckt_found = False

top_trans = []
bot_trans = []

nfin_pattern = re.compile(r'nfin\s*=\s*(\d+)')
w_pattern = re.compile(r'w\s*=\s*([\d\.]+[pn]?m)')
l_pattern = re.compile(r'l\s*=\s*([\d\.]+[pn]?m)')

net_count = {}
g_net_count = {}
sd_net_count = {}

for line in lines:
    line_strip = line.strip()
    # find .SUBCKT
    if line_strip.upper().startswith('.SUBCKT '):
        parts = line_strip.split()
        if len(parts) > 1 and parts[1].upper() == subckt_name.upper():
            subckt_found = True
            io_pins = parts[2:]
            print (io_pins)
            continue

    if subckt_found:
        if line_strip.upper().startswith('.ENDS'):
            subckt_found = False
            break

        # start with M -> transistor
        # format example: MM3 net16 A2 VSS VSS nmos_rvt w=46.0n l=16n nfin=2
        if line_strip.upper().startswith('M'):
            parts = line_strip.split()
            # parts[0]: M<name>, parts[1]: Drain, parts[2]: Gate, parts[3]: Source, parts[4]: Bulk, parts[5]: type
            # example: MM3 net16 A2 VSS VSS nmos_rvt w=... => 
            # name = MM3, D=net16, G=A2, S=VSS, B=VSS, type=nmos_rvt
            if len(parts) < 6:
                continue

            name = parts[0]
            D = parts[1]
            G = parts[2]
            S = parts[3]
            B = parts[4]
            ttype = parts[5].lower()  # pmos_rvt or nmos_rvt
            
            # multi finger handling
            param_str = ' '.join(parts[6:])
            nfin_match = nfin_pattern.search(param_str)
            nfin_val = 1
            if nfin_match:
                nfin_val = int(nfin_match.group(1))
            # handle multiple transistor
            replica_count = nfin_val // unit_fin if nfin_val % unit_fin == 0 else 1

            for net in [D, G, S]:
                net_count[net] = net_count.get(net, 0) + replica_count
            for net in [D, S]:
                sd_net_count[net] = sd_net_count.get(net, 0) + replica_count
            for net in [G]:
                g_net_count[net] = g_net_count.get(net, 0) + replica_count

            for net in [D, G, S]:
                net_count[net] = net_count.get(net, 0)
                g_net_count[net] = g_net_count.get(net, 0)
                sd_net_count[net] = sd_net_count.get(net, 0)

            for i in range(replica_count):
                if i == 0:
                    new_name = name
                else:
                    new_name = f"{name}_f{i}"
                new_nfin = unit_fin
                if 'pmos' in ttype:
                    top_trans.append((new_name, G, D, S, B, new_nfin))
                elif 'nmos' in ttype:
                    bot_trans.append((new_name, G, D, S, B, new_nfin))

print (net_count)
print (g_net_count)
print (sd_net_count)

print("Top Transistors (PMOS):")
for t in top_trans:
    print(t)

print("\nBottom Transistors (NMOS):")
for t in bot_trans:
    print(t)

num_cols = 2 * math.ceil((max(len(top_trans), len(bot_trans)) + dummy_col)/len(height)) + 1

################################## Edge generation based on num_cols
# Define columns and positions
column_positions={}
for h in height:
    column_positions[h]=[]
    column_positions[h] = [3 + 3 * i for i in range(num_cols)]
columns = list(range(len(column_positions[1])))  # Indices from 0 to 9
rows = list(range(MAX_TRACK-1, -1, -1))
dh_rows = [row + 10 for row in rows]
#print (rows)
# split pmos and nmos track
if mh_order == 'P_FIRST':
    nmos_rows = rows[:MAX_TRACK//2]
    pmos_rows = rows[MAX_TRACK//2:]
    # take care for odd track
    if MAX_TRACK % 2 != 0:
        middle_row = rows[MAX_TRACK//2]
        dh_middle_row = middle_row+10
        pmos_rows.remove(middle_row)
else:
    pmos_rows = rows[:MAX_TRACK//2]
    nmos_rows = rows[MAX_TRACK//2:]
    # take care for odd track
    if MAX_TRACK % 2 != 0:
        middle_row = rows[MAX_TRACK//2]
        dh_middle_row = middle_row+10
        nmos_rows.remove(middle_row)

dh_pmos_rows = [row + 10 for row in nmos_rows]
dh_nmos_rows = [row + 10 for row in pmos_rows]
dh_upper_rows = [row + 10 for row in upper_rows]
#print(dh_rows,dh_pmos_rows,dh_nmos_rows,dh_upper_rows)

total_rows = rows + upper_rows
via_positions = []
i = 0
while True:
    pos = int(offset + V_PITCH * (i+1))
    if pos > column_positions[1][-1]:
        break
    if pos >= 3 and pos <= column_positions[1][-1]:
        via_positions.append(pos)
    i += 1
via_indices = list(range(len(via_positions)))  # Indices of via positions
#print (f"VIA {via_positions} / {via_indices}")
print (column_positions)
print(via_positions)
col_via_pos = sorted(list(set(column_positions[1] + via_positions)))
print (col_via_pos)
# nodes
pmos_via_columns = [f"pv_{v}_{h}" for v in col_via_pos for h in height]
nmos_via_columns = [f"nv_{v}_{h}" for v in col_via_pos for h in height]
middle_via_columns = [f"middle_{v}_{h}" for v in col_via_pos for h in height]
m1_columns = [f"m1_{v}_{h}" for v in via_positions for h in height]
pmos_net = [f"pp_{3 + 3 * c}_{h}" for c in columns for h in height]
nmos_net = [f"nn_{3 + 3 * c}_{h}" for c in columns for h in height]
aligned_net = [f"ac_{3 + 3 * c}_{h}" for c in columns for h in height]

if MAX_TRACK % 2 != 0:
    connection_points = aligned_net + pmos_via_columns + nmos_via_columns + pmos_net + nmos_net + m1_columns + middle_via_columns
else :
    connection_points = aligned_net + pmos_via_columns + nmos_via_columns + pmos_net + nmos_net + m1_columns
wo_via_points = aligned_net + pmos_net + nmos_net

if len(height) > 1:
    aligned_across2 = [f"ach2_{3 + 3 * c}" for c in columns]
    aligned_across3p1 = [f"ach3p1_{3 + 3 * c}" for c in columns]
    aligned_across3p2 = [f"ach3p2_{3 + 3 * c}" for c in columns]
    aligned_across4 = [f"ach4_{3 + 3 * c}" for c in columns]
    for_dh = aligned_across2 + aligned_across3p1 + aligned_across3p2 + aligned_across4
    connection_points += for_dh
    wo_via_points += for_dh

connection_points = sorted(set(connection_points))
sorted_connection_points = sorted(connection_points,key=lambda x: int(x.split('_')[1]))

Edges = []
Edges_net = []
Edges_m0 = []
Edges_m1 = []
Edges_vh = []

for h in height:
    for col in column_positions[1]:
        Edges_net.append((f"pv_{col}_{h}", f"pp_{col}_{h}"))
        Edges_net.append((f"pv_{col}_{h}", f"ac_{col}_{h}"))
        Edges_net.append((f"nv_{col}_{h}", f"nn_{col}_{h}"))
        Edges_net.append((f"nv_{col}_{h}", f"ac_{col}_{h}"))
        if MAX_TRACK % 2 == 1:
            Edges_net.append((f"middle_{col}_{h}", f"ac_{col}_{h}"))

for col in column_positions[1]:
    if mh_order == 'P_FIRST': # PNNP
        Edges_net.append((f"nv_{col}_1", f"ach2_{col}"))
        Edges_net.append((f"nv_{col}_2", f"ach2_{col}"))
        Edges_net.append((f"pv_{col}_1", f"ach3p1_{col}"))
        Edges_net.append((f"nv_{col}_1", f"ach3p1_{col}"))
        Edges_net.append((f"nv_{col}_2", f"ach3p1_{col}"))
        Edges_net.append((f"pv_{col}_2", f"ach3p2_{col}"))
        Edges_net.append((f"nv_{col}_2", f"ach3p2_{col}"))
        Edges_net.append((f"nv_{col}_1", f"ach3p2_{col}"))
    elif mh_order == 'N_FIRST': # NPPN
        Edges_net.append((f"pv_{col}_1", f"ach2_{col}"))
        Edges_net.append((f"pv_{col}_2", f"ach2_{col}"))
        Edges_net.append((f"nv_{col}_1", f"ach3p1_{col}"))
        Edges_net.append((f"pv_{col}_1", f"ach3p1_{col}"))
        Edges_net.append((f"pv_{col}_2", f"ach3p1_{col}"))
        Edges_net.append((f"nv_{col}_2", f"ach3p2_{col}"))
        Edges_net.append((f"pv_{col}_2", f"ach3p2_{col}"))
        Edges_net.append((f"pv_{col}_1", f"ach3p2_{col}"))
    Edges_net.append((f"pv_{col}_1", f"ach4_{col}"))
    Edges_net.append((f"pv_{col}_2", f"ach4_{col}"))
    Edges_net.append((f"nv_{col}_1", f"ach4_{col}"))
    Edges_net.append((f"nv_{col}_2", f"ach4_{col}"))
    if MAX_TRACK % 2 == 1:
        Edges_net.append((f"middle_{col}_1", f"ach3p1_{col}"))
        Edges_net.append((f"middle_{col}_2", f"ach3p2_{col}"))
        Edges_net.append((f"middle_{col}_1", f"ach4_{col}"))
        Edges_net.append((f"middle_{col}_2", f"ach4_{col}"))

Edges.extend(Edges_net)

# m0 movement edge
for h in height:
    for i, v in enumerate(col_via_pos):
        #print (i,v)
        current_point = v
        if i < len(col_via_pos) - 1:
            next_point = col_via_pos[i+1]
            Edges_m0.append((f"pv_{current_point}_{h}", f"pv_{next_point}_{h}"))
            Edges_m0.append((f"nv_{current_point}_{h}", f"nv_{next_point}_{h}"))
            if MAX_TRACK % 2 == 1:
                Edges_m0.append((f"middle_{current_point}_{h}", f"middle_{next_point}_{h}"))

Edges.extend(Edges_m0)

#print (m1_columns)
# via to m1 & m2
for i, pos_i in enumerate(m1_columns):
    #print (i,pos_i)
    current_point = pos_i
    index_i = int(current_point.split('_')[1])
    h = int(current_point.split('_')[2])
    Edges_m1.append((current_point, f"pv_{index_i}_{h}"))
    Edges_m1.append((current_point, f"nv_{index_i}_{h}"))
    if MAX_TRACK % 2 == 1:
        Edges_m1.append((current_point, f"middle_{index_i}_{h}"))
    if i < len(m1_columns) - 2:
        next_point = m1_columns[i + 2]
        Edges_m1.append((current_point, next_point))

Edges.extend(Edges_m1)

for i, pos_i in enumerate(m1_columns):
    if i % 2 == 0:
        current_point = pos_i
        if i < len(m1_columns) - 1:
            next_point = m1_columns[i + 1]
            Edges_vh.append((current_point, next_point))

Edges.extend(Edges_vh)

print("Total Edges : ", Edges)

# Gate net extract
top_nets = set([t_top[1] for t_top in top_trans])
bottom_nets = set([t_bot[1] for t_bot in bot_trans])

# Shared Gate net extract
shared_net = top_nets & bottom_nets  # or top_nets.intersection(bottom_nets)
shared_net.add("dummy")

# Function to extract shared nets based on a specific index
def extract_shared_net(index, index2, top_trans, bot_trans):
    #print(top_trans,bot_trans)
    top_nets = set(t_top[index] for t_top in top_trans if t_top[index] not in power_net)
    bottom_nets = set(t_bot[index] for t_bot in bot_trans if t_bot[index] not in power_net)
    top_nets2 = set(t_top[index2] for t_top in top_trans if t_top[index2] not in power_net)
    bottom_nets2 = set(t_bot[index2] for t_bot in bot_trans if t_bot[index2] not in power_net)
    #print (top_nets,bottom_nets)
    return (top_nets | top_nets2) & (bottom_nets | bottom_nets2)

# Extract shared nets for index 0 and 2, then combine
#shared_sd = extract_shared_net(3, top_trans, bot_trans) | extract_shared_net(2, top_trans, bot_trans)
shared_sd = extract_shared_net(2, 3, top_trans, bot_trans)
#print(shared_sd,extract_shared_net(3, top_trans, bot_trans),extract_shared_net(2, top_trans, bot_trans))
#print(shared_sd)

total_pmos_sd_nets = (set(net for t in top_trans for net in [t[2], t[3]]))
total_nmos_sd_nets = (set(net for t in bot_trans for net in [t[2], t[3]]))
total_nets = (
    set(net for t in top_trans for net in [t[1], t[2], t[3]]) | 
    set(net for t in bot_trans for net in [t[1], t[2], t[3]])
)
#print(total_nets)
#print(total_pmos_sd_nets)
#print(total_nmos_sd_nets)

# Circuit Topology Optimization
print (f"------------")
print (f"analyze PMOS")
final_hierarchy_pmos = split_sets_by_paths_2(top_trans, 'VDD', shared_sd, total_pmos_sd_nets)
pmos_network={}
pmos_source={}
pmos_drain={}
add_constraints_recursive(model, final_hierarchy_pmos, pmos_network, pmos_source, pmos_drain)

print (f"------------")
print (f"analyze NMOS")
final_hierarchy_nmos = split_sets_by_paths_2(bot_trans, 'VSS', shared_sd, total_nmos_sd_nets)
nmos_network={}
nmos_source={}
nmos_drain={}
add_constraints_recursive(model, final_hierarchy_nmos, nmos_network, nmos_source, nmos_drain)

final_pmos_net_info=build_final_variables_and_constraints(pmos_source,pmos_drain,model)
final_nmos_net_info=build_final_variables_and_constraints(nmos_source,nmos_drain,model)

# Create gate_cols with even numbers starting from 2
gate_cols={}
for h in height:
    gate_cols[h] = [c for c in range(num_cols) if c % 2 == 1]
#print(gate_cols)

### Placement
# Orientation definition
def get_left_right_nets(D, S, flip):
    # flip=0: left=D, right=S
    # flip=1: left=S, right=D
    if flip == 0:
        return D, S
    else:
        return S, D

# Binary variables
c_top = {}
for i,t in enumerate(top_trans):
    name,G,D,S,B,nfin = t
    for h in height:
        for c in gate_cols[h]:
            for o in [0,1]:
                c_top[(i,h,c,o)] = model.addVar(vtype=gp.GRB.BINARY, name=f"c_top_{name}_h_{h}_c{c}_o{o}")

total_nets = (
    set(net for t in top_trans for net in [t[1], t[2], t[3]]) | 
    set(net for t in bot_trans for net in [t[1], t[2], t[3]])
)
#print(total_nets)
# Binary variables for net placement across columns
pmos_net = {}
# Extract unique nets from t[1], t[2], and t[3] in top_trans
unique_pmos_nets = set(net for t in top_trans for net in [t[1], t[2], t[3]])
unique_pmos_nets.add("dummy")
#print (unique_pmos_nets)
for h in height:
    for c in range(num_cols):
        for net in unique_pmos_nets:
            pmos_net[(net, h, c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"pmos_net_{net}_h{h}_c{c}")
        #pmos_net[("dummy",c)]  = model.addVar(vtype=gp.GRB.BINARY, name=f"pmos_dummy_{net}_c{c}")

c_bot = {}
for j,t in enumerate(bot_trans):
    name,G,D,S,B,nfin = t
    for h in height:
        for c in gate_cols[h]:
            for o in [0,1]:
                c_bot[(j,h,c,o)] = model.addVar(vtype=gp.GRB.BINARY, name=f"c_bot_{name}_h{h}_c{c}_o{o}")

# Binary variables for net placement across columns
nmos_net = {}
# Extract unique nets from t[1], t[2], and t[3] in top_trans
unique_nmos_nets = set(net for t in bot_trans for net in [t[1], t[2], t[3]])
unique_nmos_nets.add("dummy")
#print (unique_nmos_nets)
for h in height:
    for c in range(num_cols):
        for net in unique_nmos_nets:
            nmos_net[(net, h, c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"nmos_net_{net}_h{h}_c{c}")
        #nmos_net[("dummy",c)]  = model.addVar(vtype=gp.GRB.BINARY, name=f"nmos_dummy_{net}_c{c}")

# Constraint 1: one column and one orientation
# Transistor have to be placed in somewhere
for i,t in enumerate(top_trans):
    name,G,D,S,B,nfin = t
    suffix = None
    #partition is added for Mbit flip flop
    if "_" in name:
        tail = name.split("_")[-1]
        if tail.isdigit():
            suffix = int(tail)
    if i == 0: # one trasistor placed in half space to remove flip case / two way -> dont swap or half space
        # now only for DH
        print ("i==0 transistor : ",t)
        model.addConstr(gp.quicksum(c_top[(i,1,c,0)] for c in gate_cols[1]) == 1,name=f"top_assign_height_1_orient_0_{t[0]}")
        model.addConstr(gp.quicksum(c_top[(i,1,c,1)] for c in gate_cols[1]) == 0,name=f"top_assign_height_1_orient_1_{t[0]}")
        model.addConstr(gp.quicksum(c_top[(i,2,c,0)] for c in gate_cols[2]) == 0,name=f"top_assign_height_2_orient_0_{t[0]}")
        model.addConstr(gp.quicksum(c_top[(i,2,c,1)] for c in gate_cols[2]) == 0,name=f"top_assign_height_2_orient_1_{t[0]}")
    else:
        if suffix is not None:
            if partition == 'H':
                model.addConstr(gp.quicksum(c_top[(i, suffix, c, o)] for c in gate_cols[suffix] for o in [0,1]) == 1,name=f"top_assign_fixed_{name}")
                for h in height:
                    if h != suffix:
                        for c in gate_cols[h]:
                            for o in [0,1]:
                                model.addConstr(c_top[(i,h,c,o)] == 0,name=f"top_assign_zero_{name}_h{h}_c{c}_o{o}")
            elif partition == 'LR':
                if suffix == 1:
                    model.addConstr(gp.quicksum(c_top[(i, h, c, o)] for h in height for c in gate_cols[h] for o in [0,1] if c <= num_cols/2) == 1,name=f"top_assign_fixed_{name}_1")
                    model.addConstr(gp.quicksum(c_top[(i, h, c, o)] for h in height for c in gate_cols[h] for o in [0,1] if c >= num_cols/2) == 0,name=f"top_assign_fixed_{name}_0")
                if suffix == 2:
                    model.addConstr(gp.quicksum(c_top[(i, h, c, o)] for h in height for c in gate_cols[h] for o in [0,1] if c > num_cols/2) == 1,name=f"top_assign_fixed_{name}_1")
                    model.addConstr(gp.quicksum(c_top[(i, h, c, o)] for h in height for c in gate_cols[h] for o in [0,1] if c <= num_cols/2) == 0,name=f"top_assign_fixed_{name}_0")
        else:
            model.addConstr(gp.quicksum(c_top[(i,h,c,o)] for h in height for c in gate_cols[h] for o in [0,1]) == 1,name=f"top_assign_{name}")
    ######################################
    for h in height:
        for c in gate_cols[h] :
            model.addConstr(c_top[(i, h, c, 0)] + c_top[(i, h, c, 1)] <= pmos_net[(G, h, c)],name=f"pmos_net_G_{name}_h_{h}_col_{c}_o")
            for key in final_pmos_net_info[t]['source']:
                model.addConstr(c_top[(i, h, c, 0)] + final_pmos_net_info[t]['source'][key] - 1 <= pmos_net[(key, h, c - 1)],name=f"pmos_net_S_{name}_h_{h}_col_{c-1}_o0")
                model.addConstr(c_top[(i, h, c, 1)] + final_pmos_net_info[t]['source'][key] - 1 <= pmos_net[(key, h, c + 1)],name=f"pmos_net_S_{name}_h_{h}_col_{c+1}_o1")
            for key in final_pmos_net_info[t]['drain']:
                model.addConstr(c_top[(i, h, c, 0)] + final_pmos_net_info[t]['drain'][key] - 1 <= pmos_net[(key, h, c + 1)],name=f"pmos_net_D_{name}_h_{h}_col_{c+1}_o0")
                model.addConstr(c_top[(i, h, c, 1)] + final_pmos_net_info[t]['drain'][key] - 1 <= pmos_net[(key, h, c - 1)],name=f"pmos_net_D_{name}_h_{h}_col_{c-1}_o1")
            #model.addConstr(c_top[(i, h, c, 0)] <= pmos_net[(S, h, c - 1)],name=f"pmos_net_S_{name}_h_{h}_col_{c-1}_o0")
            #model.addConstr(c_top[(i, h, c, 0)] <= pmos_net[(D, h, c + 1)],name=f"pmos_net_D_{name}_h_{h}_col_{c+1}_o0")
            #model.addConstr(c_top[(i, h, c, 1)] <= pmos_net[(D, h, c - 1)],name=f"pmos_net_D_{name}_h_{h}_col_{c-1}_o1")
            #model.addConstr(c_top[(i, h, c, 1)] <= pmos_net[(S, h, c + 1)],name=f"pmos_net_S_{name}_h_{h}_col_{c+1}_o1")

for j,t in enumerate(bot_trans):
    name,G,D,S,B,nfin = t
    suffix = None
    #partition is added for Mbit flip flop
    if "_" in name:
        tail = name.split("_")[-1]
        if tail.isdigit():
            suffix = int(tail)
    if suffix is not None:
        if partition == 'H':
            model.addConstr(gp.quicksum(c_bot[(j, suffix, c, o)] for c in gate_cols[suffix] for o in [0,1]) == 1,name=f"bot_assign_fixed_{name}")
            for h in height:
                if h != suffix:
                    for c in gate_cols[h]:
                        for o in [0,1]:
                            model.addConstr(c_bot[(j,h,c,o)] == 0,name=f"bot_assign_zero_{name}_h{h}_c{c}_o{o}")
        elif partition == 'LR':
            if suffix == 1:
                model.addConstr(gp.quicksum(c_bot[(j, h, c, o)] for h in height for c in gate_cols[h] for o in [0,1] if c <= num_cols/2) == 1,name=f"bot_assign_fixed_{name}_1")
                model.addConstr(gp.quicksum(c_bot[(j, h, c, o)] for h in height for c in gate_cols[h] for o in [0,1] if c >= num_cols/2) == 0,name=f"bot_assign_fixed_{name}_0")
            elif suffix == 2:
                model.addConstr(gp.quicksum(c_bot[(j, h, c, o)] for h in height for c in gate_cols[h] for o in [0,1] if c > num_cols/2) == 1,name=f"bot_assign_fixed_{name}_1")
                model.addConstr(gp.quicksum(c_bot[(j, h, c, o)] for h in height for c in gate_cols[h] for o in [0,1] if c <= num_cols/2) == 0,name=f"bot_assign_fixed_{name}_0")
    else:
        model.addConstr(gp.quicksum(c_bot[(j,h,c,o)] for h in height for c in gate_cols[h] for o in [0,1]) == 1,name=f"bot_assign_{t[0]}")
    for h in height:
        for c in gate_cols[h]:
            model.addConstr(c_bot[(j, h, c, 0)] + c_bot[(j, h, c, 1)] <= nmos_net[(G, h, c)],name=f"nmos_net_G_{name}_h_{h}_col_{c}_o")
            for key in final_nmos_net_info[t]['source']:
                model.addConstr(c_bot[(j, h, c, 0)] + final_nmos_net_info[t]['source'][key] - 1 <= nmos_net[(key, h, c - 1)],name=f"nmos_net_S_{name}_h_{h}_col_{c-1}_o0")
                model.addConstr(c_bot[(j, h, c, 1)] + final_nmos_net_info[t]['source'][key] - 1 <= nmos_net[(key, h, c + 1)],name=f"nmos_net_S_{name}_h_{h}_col_{c+1}_o1")
            for key in final_nmos_net_info[t]['drain']:
                model.addConstr(c_bot[(j, h, c, 0)] + final_nmos_net_info[t]['drain'][key] - 1 <= nmos_net[(key, h, c + 1)],name=f"nmos_net_D_{name}_h_{h}_col_{c+1}_o0")
                model.addConstr(c_bot[(j, h, c, 1)] + final_nmos_net_info[t]['drain'][key] - 1 <= nmos_net[(key, h, c - 1)],name=f"nmos_net_D_{name}_h_{h}_col_{c-1}_o1")

            #model.addConstr(c_bot[(j, h, c, 0)] <= nmos_net[(S, h, c - 1)],name=f"nmos_net_S_{name}_h_{h}_col_{c-1}_o0")
            #model.addConstr(c_bot[(j, h, c, 0)] <= nmos_net[(D, h, c + 1)],name=f"nmos_net_D_{name}_h_{h}_col_{c+1}_o0")
            #model.addConstr(c_bot[(j, h, c, 1)] <= nmos_net[(D, h, c - 1)],name=f"nmos_net_D_{name}_h_{h}_col_{c-1}_o1")
            #model.addConstr(c_bot[(j, h, c, 1)] <= nmos_net[(S, h, c + 1)],name=f"nmos_net_S_{name}_h_{h}_col_{c+1}_o1")

# PMOS Row:
# at most one transistor can be placed in one column
for h in height:
    for c in gate_cols[h]:
        model.addConstr(gp.quicksum(c_top[(i,h,c,o)] for i in range(len(top_trans)) for o in [0,1]) <= 1,name=f"pmos_one_per_col_{c}")
        # Assign "dummy" net if no transistor is placed
        model.addConstr(gp.quicksum(c_top[(i,h,c,o)] for i in range(len(top_trans)) for o in [0,1]) + pmos_net[("dummy", h, c)] == 1,name=f"dummy_assign_pmos_col_{c}")
        for net1 in unique_pmos_nets:
            for net2 in unique_pmos_nets:
                if net1 != "dummy" and net2 != "dummy" and net1 != net2:
                    model.addConstr(pmos_net[("dummy", h, c)] + pmos_net[(net1, h, c-1)] + pmos_net[(net2, h, c+1)] <= 2 + nmos_net[("dummy", h, c)], 
                                    name=f"avoid_different_nets_{net1}_{net2}_h_{h}_col_{c}")
        model.addConstr(pmos_net[("dummy", h, c)] + pmos_net[("dummy", h, c-1)] <= 1)
        model.addConstr(pmos_net[("dummy", h, c)] + pmos_net[("dummy", h, c+1)] <= 1)
# NMOS Row:
        model.addConstr(gp.quicksum(c_bot[(j,h,c,o)] for j in range(len(bot_trans)) for o in [0,1]) <= 1,name=f"nmos_one_per_col_{c}")
        model.addConstr(gp.quicksum(c_bot[(j,h,c,o)] for j in range(len(bot_trans)) for o in [0,1]) + nmos_net[("dummy", h, c)] == 1,name=f"dummy_assign_nmos_col_{c}")
        for net1 in unique_nmos_nets:
            for net2 in unique_nmos_nets:
                if net1 != "dummy" and net2 != "dummy" and net1 != net2:
                    model.addConstr(nmos_net[("dummy", h, c)] + nmos_net[(net1, h, c-1)] + nmos_net[(net2, h, c+1)] <= 2 + pmos_net[("dummy", h, c)], 
                                    name=f"avoid_different_nets_{net1}_{net2}_h_{h}_col_{c}")
        model.addConstr(nmos_net[("dummy", h, c)] + nmos_net[("dummy", h, c-1)] <= 1)
        model.addConstr(nmos_net[("dummy", h, c)] + nmos_net[("dummy", h, c+1)] <= 1)
for h in height:
    for c in range(num_cols):
        model.addConstr(gp.quicksum(pmos_net[(net, h, c)] for net in unique_pmos_nets) == 1,name=f"pmos_one_net_per_h_{h}_col_{c}")
        model.addConstr(gp.quicksum(nmos_net[(net, h, c)] for net in unique_nmos_nets) == 1,name=f"pmos_one_net_per_h_{h}_col_{c}")

# misalign temporarily
misalign_c = {}
temp_misalign_c={} #
misalign_net_c = {}
temp_misalign_net_c = {}
dummyalign_c = {}
dummyalign_or_misalign_c = {}
clock_net=['cki','ncki']
for h in height:
    for c in gate_cols[h]:
        #print (c)
        misalign_c[h,c] = model.addVar(vtype=gp.GRB.BINARY, name=f"misalign_h_{h}_c{c}")
        temp_misalign_c[h,c] = model.addVar(vtype=gp.GRB.BINARY, name=f"temp_misalign_h_{h}_c{c}")
        dummyalign_c[h,c] = model.addVar(vtype=gp.GRB.BINARY, name=f"dummayallign_h_{h}_c{c}")
        dummyalign_or_misalign_c[h,c] = model.addVar(vtype=gp.GRB.BINARY, name=f"dummy_or_misalign_h_{h}_c{c}")
        model.addConstr(dummyalign_or_misalign_c[h,c] >= dummyalign_c[h,c],name=f"dummy_or_misalign_ge_dummy_h_{h}_{c}")
        model.addConstr(dummyalign_or_misalign_c[h,c] >= misalign_c[h,c],name=f"dummy_or_misalign_ge_mis_h_{h}_{c}")
        model.addConstr(dummyalign_or_misalign_c[h,c] <= dummyalign_c[h,c] + misalign_c[h,c],name=f"dummy_or_misalign_le_sum_h_{h}_{c}")
        for net in shared_net:
            if net in clock_net:
                #print (net)
                misalign_net_c[(net,h,c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"misalign_net_{net}_h_{h}_c{c}")
                model.addConstr(misalign_net_c[(net, h,c)] >= pmos_net[(net, h,c)] - nmos_net[(net, h,c)], name=f"misalign_c_rule1_{net}_h_{h}_c{c}")
                model.addConstr(misalign_net_c[(net, h,c)] >= nmos_net[(net, h,c)] - pmos_net[(net, h,c)], name=f"misalign_c_rule2_{net}_h_{h}_c{c}")
                model.addConstr(misalign_net_c[(net, h,c)] <= nmos_net[(net, h,c)] + pmos_net[(net, h,c)], name=f"misalign_c_rule3_{net}_h_{h}_c{c}")
                model.addConstr(misalign_net_c[(net, h,c)] <= 2 - (nmos_net[(net, h,c)] + pmos_net[(net, h,c)]), name=f"misalign_c_rule4_{net}_h_{h}_c{c}")
                model.addConstr(misalign_c[h,c] >= misalign_net_c[(net,h,c)],name=f"misalign_c_ge_misalign_net_{net}_h_{h}_c{c}")
            else :
                temp_misalign_net_c[(net,h,c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"temp_misalign_net_{net}_h_{h}_c{c}")
                model.addConstr(temp_misalign_net_c[(net, h,c)] >= pmos_net[(net, h,c)] - nmos_net[(net, h,c)], name=f"temp_misalign_c_rule1_{net}_h_{h}_c{c}")
                model.addConstr(temp_misalign_net_c[(net, h,c)] >= nmos_net[(net, h,c)] - pmos_net[(net, h,c)], name=f"temp_misalign_c_rule2_{net}_h_{h}_c{c}")
                model.addConstr(temp_misalign_net_c[(net, h,c)] <= nmos_net[(net, h,c)] + pmos_net[(net, h,c)], name=f"temp_misalign_c_rule3_{net}_h_{h}_c{c}")
                model.addConstr(temp_misalign_net_c[(net, h,c)] <= 2 - (nmos_net[(net, h,c)] + pmos_net[(net, h,c)]), name=f"temp_misalign_c_rule4_{net}_h_{h}_c{c}")
                model.addConstr(temp_misalign_c[h,c] >= temp_misalign_net_c[(net,h,c)],name=f"temp_misalign_c_ge_misalign_net_{net}_h_{h}_c{c}")
        model.addConstr(
            misalign_c[h,c] <= gp.quicksum(misalign_net_c[(net, h, c)] for net in shared_net if net in clock_net), #
            #misalign_c[c] <= gp.quicksum(misalign_net_c[(net, c)] for net in shared_net),
            name=f"misalign_c_le_sum_mis_net_h_{h}_{c}"
        )
        model.addConstr( #
            temp_misalign_c[h,c] <= gp.quicksum(temp_misalign_net_c[(net,h, c)] for net in shared_net if net not in clock_net), #
            name=f"temp_misalign_c_le_sum_mis_net_c{c}" #
        ) #
        #model.addConstr(misalign_c[h,c] <= gp.quicksum(misalign_net_c[(net,h,c)] for net in shared_net),name=f"misalign_c_le_sum_mis_net_h_{h}_c{c}")
        model.addConstr(dummyalign_c[h,c] <= pmos_net[("dummy", h,c)], name=f"dummyalign_c_rule1_h_{h}_c{c}")
        model.addConstr(dummyalign_c[h,c] <= nmos_net[("dummy", h,c)], name=f"dummyalign_c_rule2_h_{h}_c{c}")
        model.addConstr(dummyalign_c[h,c] >= pmos_net[("dummy", h,c)] + nmos_net[("dummy", h,c)] - 1, name=f"dummyalign_c_rule3_h_{h}_c{c}")

model.addConstr(gp.quicksum(misalign_c[h,c] for h in height for c in gate_cols[h]) == misalign_col, name=f"misalign_col_maximum")
model.addConstr(gp.quicksum(temp_misalign_c[h,c] for h in height for c in gate_cols[h]) == 0, name=f"temp_misalign_col_maximum") #


# gate cut constraint
consecutive = 2 #temp
for h in height:
    for i in range(len(gate_cols[h]) - consecutive + 1):
        if i == 0:
            prev_x = 0
        else:
            prev_x = dummyalign_or_misalign_c[h,gate_cols[h][i - 1]]
        block_cols = gate_cols[h][i : i + consecutive]
        model.addConstr(gp.quicksum(dummyalign_or_misalign_c[h,c] for c in block_cols) >= consecutive * (misalign_c[h,gate_cols[h][i]] - prev_x), name=f"consecutive_gate_cut_c{gate_cols[h][i]}")
        #for d in range(1, consecutive):
            #pass
            #print (i,d,gate_cols[i],gate_cols[i+d])
            #model.addConstr(misalign_c[gate_cols[i]] <= misalign_c[gate_cols[i + d]], name=f"consecutive_gate_cut_c{c}_{d}")

# flow left and right
flow_limit = MAX_TRACK + len(upper_rows)
a_l_c = {}
b_l_c = {}
for h in height:
    for c in gate_cols[h]:
        #print (c,columns,column_positions)
        for net in unique_pmos_nets:
            if net != "dummy" and net not in power_net:
                a_l_c[(net,h,c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"a_net_{net}_h_{h}_col{c}_left")
                model.addConstr(a_l_c[(net,h,c)] <= pmos_net[(net, h,c-1)],name=f"a_net_le_pmos_{net}_h_{h}_col{c}_left")
                if net in shared_sd:
                    sum_other = gp.quicksum(pmos_net[(net, h,x)]+nmos_net[(net, h,x)] for x in columns if x != c and x != (c-1))
                else:
                    sum_other = gp.quicksum(pmos_net[(net, h,x)] for x in columns if x != c and x != (c-1))
                model.addConstr(a_l_c[(net,h,c)] <= sum_other,name=f"a_net_le_sumother_{net}_h_{h}_col{c}_left")
                model.addConstr(len(columns)*(a_l_c[(net,h,c)]+1-pmos_net[(net,h,c-1)]) >= sum_other,name=f"a_net_ge_sumother_{net}_h_{h}_col{c}_left")
        for net in unique_nmos_nets:
            if net != "dummy" and net not in power_net:
                b_l_c[(net,h,c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"b_net_{net}_h_{h}_col{c}_left")
                model.addConstr(b_l_c[(net,h,c)] <= nmos_net[(net, h,c-1)],name=f"b_net_le_nmos_{net}_h_{h}_col{c}_left")
                if net in shared_sd:
                    model.addConstr(b_l_c[(net,h,c)] <= 1-a_l_c[(net,h,c)],name=f"b_net_already_{net}_h_{h}_col{c}_left")
                    sum_other = gp.quicksum(nmos_net[(net, h,x)]+pmos_net[(net,h,x)] for x in columns if x != c and x != (c-1))
                    model.addConstr(len(columns)*(b_l_c[(net,h,c)]+1-(nmos_net[(net, h,c-1)]-pmos_net[(net, h,c-1)])) >= sum_other,name=f"b_net_ge_sumother_{net}_h_{h}_col{c}_left")
                else:
                    sum_other = gp.quicksum(nmos_net[(net, h,x)] for x in columns if x != c and x != (c-1))
                    model.addConstr(len(columns)*(b_l_c[(net,h,c)]+1-nmos_net[(net, h,c-1)]) >= sum_other,name=f"b_net_ge_sumother_{net}_h_{h}_col{c}_left")
                model.addConstr(b_l_c[(net,h,c)] <= sum_other,name=f"b_net_le_sumother_{net}_h_{h}_col{c}_left")
            
a_left_c = {}
b_left_c = {}
for h in height:
    for c in gate_cols[h]:
        a_left_c[h,c] = gp.quicksum(a_l_c.get((net,h,c), 0) for net in unique_pmos_nets if net != "dummy")
        b_left_c[h,c] = gp.quicksum(b_l_c.get((net,h,c), 0) for net in unique_nmos_nets if net != "dummy")

a_r_c = {}
b_r_c = {}
for h in height:
    for c in gate_cols[h]:
        #print (c,columns,column_positions)
        for net in unique_pmos_nets:
            if net != "dummy" and net not in power_net:
                a_r_c[(net,h,c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"a_net_{net}_h_{h}_col{c}_right")
                model.addConstr(a_r_c[(net,h,c)] <= pmos_net[(net, h,c+1)],name=f"a_net_le_pmos_{net}_h_{h}_col{c}_right")
                if net in shared_sd:
                    sum_other = gp.quicksum(pmos_net[(net, h,x)]+nmos_net[(net, h,x)] for x in columns if x != c and x != (c+1))
                else:
                    sum_other = gp.quicksum(pmos_net[(net, h,x)] for x in columns if x != c and x != (c+1))
                model.addConstr(a_r_c[(net,h,c)] <= sum_other,name=f"a_net_le_sumother_{net}_h_{h}_col{c}_right")
                model.addConstr(len(columns)*(a_r_c[(net,h,c)]+1-pmos_net[(net,h,c+1)]) >= sum_other,name=f"a_net_ge_sumother_{net}_h_{h}_col{c}_right")
        for net in unique_nmos_nets:
            if net != "dummy" and net not in power_net:
                b_r_c[(net,h,c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"b_net_{net}_h_{h}_col{c}_right")
                model.addConstr(b_r_c[(net,h,c)] <= nmos_net[(net, h,c+1)],name=f"b_net_le_nmos_{net}_h_{h}_col{c}_right")
                if net in shared_sd:
                    model.addConstr(b_r_c[(net,h,c)] <= 1-a_r_c[(net,h,c)],name=f"b_net_already_{net}_h_{h}_col{c}_right")
                    sum_other = gp.quicksum(nmos_net[(net, h,x)]+pmos_net[(net,h,x)] for x in columns if x != c and x != (c+1))
                    model.addConstr(len(columns)*(b_r_c[(net,h,c)]+1-(nmos_net[(net, h,c+1)]-pmos_net[(net, h,c+1)])) >= sum_other,name=f"b_net_ge_sumother_{net}_h_{h}_col{c}_right")
                else:  
                    sum_other = gp.quicksum(nmos_net[(net, h,x)] for x in columns if x != c and x != (c+1))
                    model.addConstr(len(columns)*(b_r_c[(net,h,c)]+1-nmos_net[(net, h,c+1)]) >= sum_other,name=f"b_net_ge_sumother_{net}_h_{h}_col{c}_right")
                model.addConstr(b_r_c[(net,h,c)] <= sum_other,name=f"b_net_le_sumother_{net}_h_{h}_col{c}_right")

a_right_c = {}
b_right_c = {}
for h in height:
    for c in gate_cols[h]:
        a_right_c[h,c] = gp.quicksum(a_r_c.get((net,h,c), 0) for net in unique_pmos_nets if net != "dummy")
        b_right_c[h,c] = gp.quicksum(b_r_c.get((net,h,c), 0) for net in unique_nmos_nets if net != "dummy")

a_c = {}
b_c = {}
for h in height:
    for c in gate_cols[h]:
        a_c[h,c] = model.addVar(vtype=gp.GRB.BINARY, name=f"a_{net}_h_{h}_col{c}_final")
        b_c[h,c] = model.addVar(vtype=gp.GRB.BINARY, name=f"b_{net}_h_{h}_col{c}_final")
        model.addConstr(a_c[h,c]>=a_left_c[h,c],name=f"a_{net}_h_{h}_col{c}_rule1")
        model.addConstr(a_c[h,c]>=a_right_c[h,c],name=f"a_{net}_h_{h}_col{c}_rule2")
        model.addConstr(a_c[h,c]<=a_left_c[h,c]+a_right_c[h,c],name=f"a_{net}_h_{h}_col{c}_rule3")
        model.addConstr(b_c[h,c]>=b_left_c[h,c],name=f"b_{net}_h_{h}_col{c}_rule1")
        model.addConstr(b_c[h,c]>=b_right_c[h,c],name=f"b_{net}_h_{h}_col{c}_rule2")
        model.addConstr(b_c[h,c]<=b_left_c[h,c]+b_right_c[h,c],name=f"b_{net}_h_{h}_col{c}_rule3")

e_net_c = {}
e_c = {}
for h in height:
    for cidx, c in enumerate(gate_cols[h]):
        tmp_list = []
        left_cols  = [x for x in columns if x <= c-2]
        right_cols = [x for x in columns if x >= c+2]
        for net in total_nets:
            if net not in power_net:
                ename = f"e_net_{net}_h_{h}_col{c}"
                ev = model.addVar(vtype=gp.GRB.BINARY, name=ename)
                left_exist = model.addVar(vtype=gp.GRB.BINARY, name=f"left_{net}_exist_{h}_{c}")
                right_exist = model.addVar(vtype=gp.GRB.BINARY, name=f"right_{net}_exist_{h}_{c}")
                if net in shared_net:
                    left_sum = gp.quicksum(pmos_net[(net, h,x)] + nmos_net[(net,h, x)] for x in left_cols)
                    right_sum = gp.quicksum(pmos_net[(net, h,x)] + nmos_net[(net,h, x)] for x in right_cols)
                elif net in unique_pmos_nets:
                    left_sum = gp.quicksum(pmos_net[(net, h,x)] for x in left_cols)
                    right_sum = gp.quicksum(pmos_net[(net, h,x)] for x in right_cols)
                elif net in unique_nmos_nets:
                    left_sum = gp.quicksum(nmos_net[(net, h,x)] for x in left_cols)
                    right_sum = gp.quicksum(nmos_net[(net, h,x)] for x in right_cols)
                model.addConstr(left_exist <= left_sum,f"left_exist_rule1_{h}_{c}_{net}")
                model.addConstr(len(columns)*left_exist >= left_sum,f"left_exist_rule2_{h}_{c}_{net}")                
                model.addConstr(right_exist <= right_sum,f"right_exist_rule1_{h}_{c}_{net}")
                model.addConstr(len(columns)*right_exist >= right_sum,f"right_exist_rule2_{h}_{c}_{net}")
                model.addConstr(ev <= left_exist,f"min_cut_rule1_{h}_{c}_{net}")
                model.addConstr(ev <= right_exist,f"min_cut_rule2_{h}_{c}_{net}")
                model.addConstr(len(columns)*ev >= left_exist+right_exist-1,f"min_cut_rule3_{h}_{c}_{net}")
                e_net_c[(net,h,c)] = ev
                tmp_list.append(ev)
            e_c[h,c] = gp.quicksum(tmp_list)

flow_estimator={}
for h in height:
    for c in gate_cols[h]:
        track_expr       = a_c[h,c] + b_c[h,c] + (1 + misalign_c[h,c])
        track_ext_expr   = track_expr + e_c[h,c]
        flow_estimator[h,c] = track_ext_expr
        model.addConstr(track_expr <= MAX_TRACK,name=f"track_limit_h{h}_col{c}")
        model.addConstr(track_ext_expr <= flow_limit,name=f"track_plus_e_limit_h{h}_col{c}")

## Routing Start
def get_list_set(x, MAR, num_cols):
    list_set = []
    #print (x,MAR,num_cols)
    for start in range(x - MAR, x):
        if start < -1:
            continue
        seq_full = list(range(start, start + (MAR+2)))
        seq_clipped = [c for c in seq_full if 0 <= c < num_cols]

        if x not in seq_clipped or len(seq_clipped) < MAR+1:
            continue

        list_set.append(seq_clipped)

    return list_set

### Routing variable
v_n_v = {}       # Binary variables: net n places a via at via index v
vh_n_v = {}       # Binary variables: net n places a via at via index v
t_c = {}         # Integer variables: total track cost at column c
t_c_r = {}       # Integer variables: total track cost at column c, row r
t_n_c_r = {}     # Binary variables: net n uses track at column c, row r
ut_c = {}        # Binary variables: upper track cost at column c
ut_c_r = {}      # Binary variables: upper track cost at column c, row r
ut_n_c_r = {}    # Binary variables: net n uses upper track cost at column c, row r

# for flow
sum_actives_vars={}   # To store sum_active_vars variables
is_root_node = {}     # Define is_root_node variables
indicator_i_vars = {} # Define indicator_i_vars
net_flow={}           # Flow conservation constraints
f_n_c_r = {}     # Integer variables: net n flow variable for edge at column c and row r
f_n_c_ur = {}    # Integer variables: net n flow variable for edge at column c and upper row ur
y_n_c_r = {}     # Binary variables: net n flow variable row selection at column c
flow_cap={}
cap_i={}
io_marker={}
c_mar_row={}
case={}
min_indicator={} #bbox, root node
max_indicator={} #bbox
max_bbox={} #bbox

for c in columns:
    for h in height:
        t_c[h,c] = model.addVar(vtype=gp.GRB.CONTINUOUS, name=f"t_c_{h}_{c}")
        ut_c[h,c] = model.addVar(vtype=gp.GRB.CONTINUOUS, name=f"ut_c_{h}_{c}")
    for r in rows+dh_rows:
        t_c_r[c, r] = model.addVar(vtype=gp.GRB.CONTINUOUS, name=f"t_c_{c}_{r}")
    for r in upper_rows+dh_upper_rows:
        ut_c_r[c, r] = model.addVar(vtype=gp.GRB.CONTINUOUS, name=f"ut_c_{c}_{r}")

# eol
new_net_name = 'eol'
t_n_c_r[new_net_name] = model.addVars(columns, rows+dh_rows, vtype=gp.GRB.BINARY, name=f"t_{new_net_name}_c_r")
ut_n_c_r[new_net_name] = model.addVars(columns, upper_rows+dh_upper_rows, vtype=gp.GRB.BINARY, name=f"ut_{new_net_name}_c_r")

### Routing constraint

def get_positions(c, height):
    base_positions = {
        "pp": [f"pp_{3 + 3 * c}_1"],
        "nn": [f"nn_{3 + 3 * c}_1"],
        "ac": [f"ac_{3 + 3 * c}_1"]
    } # for single height
    if height == [1, 2]:  # Include additional positions for height=[1,2]
        base_positions["pp"].append(f"pp_{3 + 3 * c}_2")
        base_positions["nn"].append(f"nn_{3 + 3 * c}_2")
        base_positions["ac"].append(f"ac_{3 + 3 * c}_2")
        base_positions["mh"] = [
            f"ach2_{3 + 3 * c}", f"ach3p1_{3 + 3 * c}",
            f"ach3p2_{3 + 3 * c}", f"ach4_{3 + 3 * c}"
        ]
    return base_positions

def get_positions_list(c, height):
    base_positions = {
        "pp": [f"pp_{3 + 3 * c}_1"],
        "nn": [f"nn_{3 + 3 * c}_1"],
        "ac": [f"ac_{3 + 3 * c}_1"]
    }
    if height == [1, 2]:  # Include additional positions for height=[1,2]
        base_positions["pp"].append(f"pp_{3 + 3 * c}_2")
        base_positions["nn"].append(f"nn_{3 + 3 * c}_2")
        base_positions["ac"].append(f"ac_{3 + 3 * c}_2")
        base_positions["mh"] = [
            f"ach2_{3 + 3 * c}", f"ach3p1_{3 + 3 * c}",
            f"ach3p2_{3 + 3 * c}", f"ach4_{3 + 3 * c}"
        ]
    return [pos for sublist in base_positions.values() for pos in sublist]

# placed net -> indicator pp nn ac
for net in total_nets:
    if net not in power_net:
        if net in io_pins:
            io_marker[net]=1
        else :
            io_marker[net]=0
        t_n_c_r[net] = model.addVars(columns, rows+dh_rows, vtype=gp.GRB.BINARY, name=f"t_{net}_c_r")
        v_n_v[net] = model.addVars(height, via_indices, vtype=gp.GRB.BINARY, name=f"v_{net}_h_v")
        vh_n_v[net] = model.addVars(via_indices, vtype=gp.GRB.BINARY, name=f"v_{net}_vh")
        ut_n_c_r[net] = model.addVars(columns, upper_rows+dh_upper_rows, vtype=gp.GRB.BINARY, name=f"ut_{net}_c_r")
        cap = g_net_count[net] + math.ceil(sd_net_count[net]/2) + dummy_padding
        min_indicator[net] = model.addVar(vtype=gp.GRB.INTEGER, lb=0, ub=num_cols - 1, name=f"min_indicator_{net}")
        max_bbox[net] = model.addVar(vtype=gp.GRB.INTEGER, lb=0, ub=num_cols - 1, name=f"max_bbox_{net}")

        for c in range(num_cols) :
            positions = get_positions(c,height)
            for key, pos_list in positions.items():
                for pos in pos_list:
                    indicator_i_vars[net, pos] = model.addVar(vtype=gp.GRB.BINARY, name=f"indicator_{net}_{pos}")
                    is_root_node[net, pos] = model.addVar(vtype=gp.GRB.BINARY, name=f"root_node_{net}_{pos}")
                    max_indicator[net, pos] = model.addVar(vtype=gp.GRB.BINARY, name=f"max_indicator_{net}_{pos}")

                    model.addConstr(indicator_i_vars[net, pos] >= is_root_node[net, pos], name=f"root_find_{net}_{pos}")
                    model.addConstr(indicator_i_vars[net, pos] >= max_indicator[net, pos], name=f"max_indicator_find_{net}_{pos}")
            
            model.addConstr(gp.quicksum(indicator_i_vars[net,pos] for key, pos_list in positions.items() for pos in pos_list) <=3 )
            aligned_column_is_there = gp.quicksum(indicator_i_vars[net,pos] for key, pos_list in positions.items() if key == 'mh' for pos in pos_list)
            #print (aligned_column_is_there)
            model.addConstr(aligned_column_is_there <=1)

            pos_mh = positions['mh']
            #print (pos_mh,net,indicator_i_vars)

            if net in unique_pmos_nets and net in unique_nmos_nets:
                model.addConstr(indicator_i_vars[net, pos_mh[3]] >= nmos_net[(net, 1, c)]+pmos_net[(net, 1, c)]+nmos_net[(net, 2, c)]+pmos_net[(net, 2, c)] - 3, name=f"lower_bound_{net}_{pos_mh[3]}")
                model.addConstr(indicator_i_vars[net, pos_mh[3]] <= nmos_net[(net, 1, c)], name=f"upper_bound_v1_{net}_{pos_mh[3]}")
                model.addConstr(indicator_i_vars[net, pos_mh[3]] <= nmos_net[(net, 2, c)], name=f"upper_bound_v2_{net}_{pos_mh[3]}")
                model.addConstr(indicator_i_vars[net, pos_mh[3]] <= pmos_net[(net, 1, c)], name=f"upper_bound_v3_{net}_{pos_mh[3]}")
                model.addConstr(indicator_i_vars[net, pos_mh[3]] <= pmos_net[(net, 2, c)], name=f"upper_bound_v4_{net}_{pos_mh[3]}")
                
                if mh_order == 'P_FIRST':
                    model.addConstr(indicator_i_vars[net, pos_mh[2]] >= nmos_net[(net, 1, c)]+pmos_net[(net, 2, c)]+nmos_net[(net, 2, c)] - (2*indicator_i_vars[net, pos_mh[3]]) - 2, name=f"lower_bound_{net}_{pos_mh[2]}")
                    model.addConstr(indicator_i_vars[net, pos_mh[2]] <= nmos_net[(net, 1, c)], name=f"upper_bound_v1_{net}_{pos_mh[2]}")
                    model.addConstr(indicator_i_vars[net, pos_mh[2]] <= pmos_net[(net, 2, c)], name=f"upper_bound_v2_{net}_{pos_mh[2]}")
                    model.addConstr(indicator_i_vars[net, pos_mh[2]] <= nmos_net[(net, 2, c)], name=f"upper_bound_v3_{net}_{pos_mh[2]}")

                    model.addConstr(indicator_i_vars[net, pos_mh[1]] >= nmos_net[(net, 1, c)]+pmos_net[(net, 1, c)]+nmos_net[(net, 2, c)] - (2*indicator_i_vars[net, pos_mh[3]]) - 2, name=f"lower_bound_{net}_{pos_mh[1]}")
                    model.addConstr(indicator_i_vars[net, pos_mh[1]] <= pmos_net[(net, 1, c)], name=f"upper_bound_v1_{net}_{pos_mh[1]}")
                    model.addConstr(indicator_i_vars[net, pos_mh[1]] <= nmos_net[(net, 1, c)], name=f"upper_bound_v2_{net}_{pos_mh[1]}")
                    model.addConstr(indicator_i_vars[net, pos_mh[1]] <= nmos_net[(net, 2, c)], name=f"upper_bound_v3_{net}_{pos_mh[1]}")

                    model.addConstr(indicator_i_vars[net, positions["ac"][1]] >= -1 + pmos_net[(net, 2, c)] + nmos_net[(net, 2, c)] - nmos_net[(net, 1, c)], name=f"lower_bound_{net}_{positions['ac'][1]}")
                    model.addConstr(indicator_i_vars[net, positions["ac"][1]] <= pmos_net[(net, 2, c)], name=f"upper_bound_v1_{net}_{positions['ac'][1]}")
                    model.addConstr(indicator_i_vars[net, positions["ac"][1]] <= nmos_net[(net, 2, c)], name=f"upper_bound_v2_{net}_{positions['ac'][1]}")
                    model.addConstr(indicator_i_vars[net, positions["ac"][1]] <= 1-nmos_net[(net, 1, c)], name=f"upper_bound_v3_{net}_{positions['ac'][1]}")

                    model.addConstr(indicator_i_vars[net, positions["ac"][0]] >= -1 + pmos_net[(net, 1, c)] + nmos_net[(net, 1, c)] - nmos_net[(net, 2, c)], name=f"lower_bound_{net}_{positions['ac'][0]}")
                    model.addConstr(indicator_i_vars[net, positions["ac"][0]] <= pmos_net[(net, 1, c)], name=f"upper_bound_v1_{net}_{positions['ac'][0]}")
                    model.addConstr(indicator_i_vars[net, positions["ac"][0]] <= nmos_net[(net, 1, c)], name=f"upper_bound_v2_{net}_{positions['ac'][0]}")
                    model.addConstr(indicator_i_vars[net, positions["ac"][0]] <= 1-nmos_net[(net, 2, c)], name=f"upper_bound_v3_{net}_{positions['ac'][0]}")

                    model.addConstr(indicator_i_vars[net, positions["pp"][0]] == pmos_net[(net, 1, c)] - (indicator_i_vars[net, pos_mh[3]]+indicator_i_vars[net, pos_mh[1]]+indicator_i_vars[net, positions['ac'][0]]), name=f"combined_net_{net}_{positions['pp'][0]}")
                    model.addConstr(indicator_i_vars[net, positions["nn"][0]] == nmos_net[(net, 1, c)] - (indicator_i_vars[net, pos_mh[3]]+indicator_i_vars[net, pos_mh[2]]+indicator_i_vars[net, pos_mh[1]]+indicator_i_vars[net, pos_mh[0]]+indicator_i_vars[net, positions['ac'][0]]), name=f"combined_net_{net}_{positions['nn'][0]}")
                    model.addConstr(indicator_i_vars[net, positions["pp"][1]] == pmos_net[(net, 2, c)] - (indicator_i_vars[net, pos_mh[3]]+indicator_i_vars[net, pos_mh[2]]+indicator_i_vars[net, positions['ac'][1]]), name=f"combined_net_{net}_{positions['pp'][1]}")
                    model.addConstr(indicator_i_vars[net, positions["nn"][1]] == nmos_net[(net, 2, c)] - (indicator_i_vars[net, pos_mh[3]]+indicator_i_vars[net, pos_mh[2]]+indicator_i_vars[net, pos_mh[1]]+indicator_i_vars[net, pos_mh[0]]+indicator_i_vars[net, positions['ac'][1]]), name=f"combined_net_{net}_{positions['nn'][1]}")

                else :
                    model.addConstr(indicator_i_vars[net, pos_mh[2]] >= pmos_net[(net, 1, c)]+nmos_net[(net, 2, c)]+pmos_net[(net, 2, c)] - (2*indicator_i_vars[net, pos_mh[3]]) - 2, name=f"lower_bound_{net}_{pos_mh[2]}")
                    model.addConstr(indicator_i_vars[net, pos_mh[2]] <= pmos_net[(net, 1, c)], name=f"upper_bound_v1_{net}_{pos_mh[2]}")
                    model.addConstr(indicator_i_vars[net, pos_mh[2]] <= nmos_net[(net, 2, c)], name=f"upper_bound_v2_{net}_{pos_mh[2]}")
                    model.addConstr(indicator_i_vars[net, pos_mh[2]] <= pmos_net[(net, 2, c)], name=f"upper_bound_v3_{net}_{pos_mh[2]}")

                    model.addConstr(indicator_i_vars[net, pos_mh[1]] >= pmos_net[(net, 1, c)]+nmos_net[(net, 1, c)]+pmos_net[(net, 2, c)] - (2*indicator_i_vars[net, pos_mh[3]]) - 2, name=f"lower_bound_{net}_{pos_mh[1]}")
                    model.addConstr(indicator_i_vars[net, pos_mh[1]] <= nmos_net[(net, 1, c)], name=f"upper_bound_v1_{net}_{pos_mh[1]}")
                    model.addConstr(indicator_i_vars[net, pos_mh[1]] <= pmos_net[(net, 1, c)], name=f"upper_bound_v2_{net}_{pos_mh[1]}")
                    model.addConstr(indicator_i_vars[net, pos_mh[1]] <= pmos_net[(net, 2, c)], name=f"upper_bound_v3_{net}_{pos_mh[1]}")

                    model.addConstr(indicator_i_vars[net, positions["ac"][1]] >= -1 + nmos_net[(net, 2, c)] + pmos_net[(net, 2, c)] - pmos_net[(net, 1, c)], name=f"lower_bound_{net}_{positions['ac'][1]}")
                    model.addConstr(indicator_i_vars[net, positions["ac"][1]] <= nmos_net[(net, 2, c)], name=f"upper_bound_v1_{net}_{positions['ac'][1]}")
                    model.addConstr(indicator_i_vars[net, positions["ac"][1]] <= pmos_net[(net, 2, c)], name=f"upper_bound_v2_{net}_{positions['ac'][1]}")
                    model.addConstr(indicator_i_vars[net, positions["ac"][1]] <= 1-pmos_net[(net, 1, c)], name=f"upper_bound_v3_{net}_{positions['ac'][1]}")

                    model.addConstr(indicator_i_vars[net, positions["ac"][0]] >= -1 + nmos_net[(net, 1, c)] + pmos_net[(net, 1, c)] - pmos_net[(net, 2, c)], name=f"lower_bound_{net}_{positions['ac'][0]}")
                    model.addConstr(indicator_i_vars[net, positions["ac"][0]] <= nmos_net[(net, 1, c)], name=f"upper_bound_v1_{net}_{positions['ac'][0]}")
                    model.addConstr(indicator_i_vars[net, positions["ac"][0]] <= pmos_net[(net, 1, c)], name=f"upper_bound_v2_{net}_{positions['ac'][0]}")
                    model.addConstr(indicator_i_vars[net, positions["ac"][0]] <= 1-pmos_net[(net, 2, c)], name=f"upper_bound_v3_{net}_{positions['ac'][0]}")

                    model.addConstr(indicator_i_vars[net, positions["pp"][0]] == pmos_net[(net, 1, c)] - (indicator_i_vars[net, pos_mh[3]]+indicator_i_vars[net, pos_mh[2]]+indicator_i_vars[net, pos_mh[1]]+indicator_i_vars[net, pos_mh[0]]+indicator_i_vars[net, positions['ac'][0]]), name=f"combined_net_{net}_{positions['pp'][0]}")
                    model.addConstr(indicator_i_vars[net, positions["nn"][0]] == nmos_net[(net, 1, c)] - (indicator_i_vars[net, pos_mh[3]]+indicator_i_vars[net, pos_mh[1]]+indicator_i_vars[net, positions['ac'][0]]), name=f"combined_net_{net}_{positions['nn'][0]}")
                    model.addConstr(indicator_i_vars[net, positions["pp"][1]] == pmos_net[(net, 2, c)] - (indicator_i_vars[net, pos_mh[3]]+indicator_i_vars[net, pos_mh[2]]+indicator_i_vars[net, pos_mh[1]]+indicator_i_vars[net, pos_mh[0]]+indicator_i_vars[net, positions['ac'][1]]), name=f"combined_net_{net}_{positions['pp'][1]}")
                    model.addConstr(indicator_i_vars[net, positions["nn"][1]] == nmos_net[(net, 2, c)] - (indicator_i_vars[net, pos_mh[3]]+indicator_i_vars[net, pos_mh[2]]+indicator_i_vars[net, positions['ac'][1]]), name=f"combined_net_{net}_{positions['nn'][1]}")
            else:
                if net in unique_pmos_nets:
                    if mh_order == 'N_FIRST':
                        model.addConstr(indicator_i_vars[net, pos_mh[0]] >= -1 + pmos_net[(net, 1, c)]+pmos_net[(net, 2, c)], name=f"lower_bound_v1_{net}_{pos_mh[0]}")
                        model.addConstr(indicator_i_vars[net, pos_mh[0]] <= pmos_net[(net, 1, c)], name=f"upper_bound_v1_{net}_{pos_mh[0]}")
                        model.addConstr(indicator_i_vars[net, pos_mh[0]] <= pmos_net[(net, 2, c)], name=f"upper_bound_v2_{net}_{pos_mh[0]}")
                        for key, pos_list in positions.items():
                            for pos in pos_list:
                                if key =='mh' and pos.startswith('ach2'):
                                    pass
                                elif key == 'pp':
                                    pass
                                else:
                                    model.addConstr(indicator_i_vars[net, pos] == 0, name=f"indicator_def_up_{net}_{pos}")
                    else :
                        for key, pos_list in positions.items():
                            for pos in pos_list:
                                if key != 'pp':
                                    model.addConstr(indicator_i_vars[net, pos] == 0, name=f"indicator_def_up_{net}_{pos}")
                    for h in height:
                        model.addConstr(indicator_i_vars[net,positions["pp"][h-1]] == pmos_net[(net,h,c)]-indicator_i_vars[net, pos_mh[0]], name=f"link_pmos_net_and_indicator_{net}_{net,positions['pp'][h-1]}")

                if net in unique_nmos_nets:
                    if mh_order == 'P_FIRST':
                        model.addConstr(indicator_i_vars[net, pos_mh[0]] >= -1 + nmos_net[(net, 1, c)]+nmos_net[(net, 2, c)], name=f"lower_bound_v1_{net}_{pos_mh[0]}")
                        model.addConstr(indicator_i_vars[net, pos_mh[0]] <= nmos_net[(net, 1, c)], name=f"upper_bound_v1_{net}_{pos_mh[0]}")
                        model.addConstr(indicator_i_vars[net, pos_mh[0]] <= nmos_net[(net, 2, c)], name=f"upper_bound_v2_{net}_{pos_mh[0]}")
                        for key, pos_list in positions.items():
                            for pos in pos_list:
                                if key =='mh' and pos.startswith('ach2'):
                                    pass
                                elif key == 'nn':
                                    pass
                                else:
                                    model.addConstr(indicator_i_vars[net, pos] == 0, name=f"indicator_def_un_{net}_{pos}")
                    else :
                        for key, pos_list in positions.items():
                            for pos in pos_list:
                                if key != 'nn':
                                    model.addConstr(indicator_i_vars[net, pos] == 0, name=f"indicator_def_un_{net}_{pos}")
                    for h in height:
                        model.addConstr(indicator_i_vars[net,positions["nn"][h-1]] == nmos_net[(net,h,c)]-indicator_i_vars[net, pos_mh[0]], name=f"link_nmos_net_and_indicator_{net}_{net,positions['nn'][h-1]}")

            for key, pos_list in positions.items():
                for pos in pos_list:
                    # root node minimun
                    model.addConstr(min_indicator[net] <= c + (1 - indicator_i_vars[net, pos]) * num_cols,name=f"min_indicator_{pos}_{net}_{c}")
                    model.addConstr(min_indicator[net] <= c + (1 - indicator_i_vars[net, pos]) * num_cols,name=f"min_indicator_{pos}_{net}_{c}")
                    model.addConstr(min_indicator[net] <= c + (1 - indicator_i_vars[net, pos]) * num_cols,name=f"min_indicator_{pos}_{net}_{c}")
                    model.addConstr(is_root_node[net, pos]*c <= min_indicator[net], name=f"root_node_{pos}_{net}_{c}")
                    model.addConstr(is_root_node[net, pos]*c <= min_indicator[net], name=f"root_node_{pos}_{net}_{c}")
                    model.addConstr(is_root_node[net, pos]*c <= min_indicator[net], name=f"root_node_{pos}_{net}_{c}")
                    # maximun bbox
                    model.addConstr(max_bbox[net] >= c - (1 - indicator_i_vars[net, pos]) * num_cols,name=f"max_bbox_{pos}_{net}_{c}")
                    model.addConstr(max_bbox[net] >= c - (1 - indicator_i_vars[net, pos]) * num_cols,name=f"max_bbox_{pos}_{net}_{c}")
                    model.addConstr(max_bbox[net] >= c - (1 - indicator_i_vars[net, pos]) * num_cols,name=f"max_bbox_{pos}_{net}_{c}")
                    model.addConstr((num_cols-1)*(1-max_indicator[net, pos])+max_indicator[net, pos]*c >= max_bbox[net], name=f"max_indicator_match_{pos}_{net}_{c}")
                    model.addConstr((num_cols-1)*(1-max_indicator[net, pos])+max_indicator[net, pos]*c >= max_bbox[net], name=f"max_indicator_match_{pos}_{net}_{c}")
                    model.addConstr((num_cols-1)*(1-max_indicator[net, pos])+max_indicator[net, pos]*c >= max_bbox[net], name=f"max_indicator_match_{pos}_{net}_{c}")

        sum_actives = gp.quicksum(indicator_i_vars[net, pos] for c in range(num_cols) for pos in get_positions_list(c, height))
        #sum_actives = gp.quicksum(indicator_i_vars[net,f"pp_{3 + 3 * c}_1"]+indicator_i_vars[net,f"nn_{3 + 3 * c}_1"]+indicator_i_vars[net,f"ac_{3 + 3 * c}_1"]+indicator_i_vars[net,f"pp_{3 + 3 * c}_2"]+indicator_i_vars[net,f"nn_{3 + 3 * c}_2"]+indicator_i_vars[net,f"ac_{3 + 3 * c}_2"]+indicator_i_vars[net,f"ach2_{3 + 3 * c}"]+indicator_i_vars[net,f"ach3p1_{3 + 3 * c}"]+indicator_i_vars[net,f"ach3p2_{3 + 3 * c}"]+indicator_i_vars[net,f"ach4_{3 + 3 * c}"] for c in range(num_cols))
        sum_actives_vars[(net)] = sum_actives
        model.addConstr(gp.quicksum(is_root_node[net, pos] for c in range(num_cols) for pos in get_positions_list(c, height)) == 1, name=f"one_root_node_enable_{net}")
        model.addConstr(gp.quicksum(max_indicator[net, pos] for c in range(num_cols) for pos in get_positions_list(c, height)) == 1, name=f"one_max_indicator_enable_{net}")
        #model.addConstr(gp.quicksum(is_root_node[net,f"pp_{3 + 3 * c}_1"]+is_root_node[net,f"nn_{3 + 3 * c}_1"]+is_root_node[net,f"ac_{3 + 3 * c}_1"]+is_root_node[net,f"pp_{3 + 3 * c}_2"]+is_root_node[net,f"nn_{3 + 3 * c}_2"]+is_root_node[net,f"ac_{3 + 3 * c}_2"]+is_root_node[net,f"ach2_{3 + 3 * c}"]+is_root_node[net,f"ach3p1_{3 + 3 * c}"]+is_root_node[net,f"ach3p2_{3 + 3 * c}"]+is_root_node[net,f"ach4_{3 + 3 * c}"] for c in range(num_cols)) == 1, name=f"one_root_node_enable_{net}")
        #model.addConstr(gp.quicksum(max_indicator[net,f"pp_{3 + 3 * c}_1"]+max_indicator[net,f"nn_{3 + 3 * c}_1"]+max_indicator[net,f"ac_{3 + 3 * c}_1"]+max_indicator[net,f"pp_{3 + 3 * c}_2"]+max_indicator[net,f"nn_{3 + 3 * c}_2"]+max_indicator[net,f"ac_{3 + 3 * c}_2"]+max_indicator[net,f"ach2_{3 + 3 * c}"]+max_indicator[net,f"ach3p1_{3 + 3 * c}"]+max_indicator[net,f"ach3p2_{3 + 3 * c}"]+max_indicator[net,f"ach4_{3 + 3 * c}"] for c in range(num_cols)) == 1, name=f"one_max_indicator_enable_{net}")

        if routing_switch == 'on':
        #f_n_c_r[net] = model.addVars(Edges_m0, rows, lb=-cap, ub=cap, vtype=gp.GRB.INTEGER, name=f"f_{net}_edge_r")
	        f_n_c_r[net] = {}
	        f_n_c_ur[net]= {}
	        #y_n_c_r[net] = model.addVars(Edges_m0, rows, vtype=gp.GRB.BINARY, name=f"y_{net}_edge_r")
	        y_n_c_r[net] = {}
	        #flow_cap[net] = model.addVars(Edges_m0, rows, vtype=gp.GRB.INTEGER, name=f"flow_cap_{net}_edge")
	        #flow_cap2[net] = {}
	        
	        # id_detector, io_marker[net]  / # sum_acitves variable is always geq than 1
	        # sum_actives == 1 -> io_detector is 0 but only when io_marker[net] is 1 -> io_detector is 1
	        # sum_actives > 1 -> io_detector is 1.
	        big=len(columns)
	        io_detector = model.addVar(vtype=gp.GRB.BINARY, name=f"io_detector_{net}") # 1 -> iopin / 0 -> don't care
	        model.addConstr(big*io_detector >= sum_actives - 1 + io_marker[net],name=f"y_detector_dtermine_lb_{net}_{j}")
	        model.addConstr(io_detector <= sum_actives - 1 + io_marker[net],name=f"y_detector_dtermine_ub_{net}_{j}")
	
	        for edge in Edges_net:
	            i, j = edge
	            #print (net,i,j,cap)
	            var_name = f"y_{net}_edge_connector_{i}_{j}_co"
	            flow_var_name = f"f_{net}_edge_connector_{i}_{j}_co"
	            y_n_c_r[net][i, j, 'co'] = model.addVar(vtype=gp.GRB.BINARY, name=var_name)
	            model.addConstr(y_n_c_r[net][i, j, 'co'] <= indicator_i_vars[net,j], f"on_off_constraint_by_indicator_{net}_{i}_{j}_co")
	            model.addConstr(y_n_c_r[net][i, j, 'co'] <= io_detector, f"on_off_constraint_by_sum_actives_{net}_{i}_{j}_co")
	            model.addConstr(y_n_c_r[net][i, j, 'co'] >= indicator_i_vars[net,j]+io_detector-1, f"on_off_constraint_by_mixing_{net}_{i}_{j}_co")
	            f_n_c_r[net][i, j, 'co'] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.CONTINUOUS, name=flow_var_name)
	            model.addConstr(f_n_c_r[net][i, j, 'co'] <= cap * y_n_c_r[net][i, j, 'co'], name=f'edge_flow_ub_{net}_{i}_{j}_ve')
	            model.addConstr(f_n_c_r[net][i, j, 'co'] >= -cap * y_n_c_r[net][i, j, 'co'],name=f'edge_flow_lb_{net}_{i}_{j}_ve')
	        
	        # MAR !!!
	        #if io_marker[net] == 1:
	        for c in range(num_cols) :
	            positions = get_positions(c,height)
	            target_list = get_list_set(c,M_MAR,num_cols) # 2 to 3 gear ratio -> divided 3
	            #print (net,c,target_list)
	            for key, pos_list in positions.items():
	                for j in pos_list:
	                    j_prefix = j.split('_')[0]
	                    if key != 'mh':
	                        h = int(j.split('_')[2])
	                    else :
	                        h = int(2)
	                    #print (c, j, j_prefix, target_list, len(target_list))
	                    if key == 'ac':
	                        if h == 1:
	                            target_rows = rows
	                        elif h == 2:
	                            target_rows = dh_rows
	                    elif key == 'pp':
	                        if h == 1:
	                            target_rows = pmos_rows
	                        elif h == 2:
	                            target_rows = dh_pmos_rows
	                    elif key == 'nn':
	                        if h == 1:
	                            target_rows = nmos_rows
	                        elif h == 2:
	                            target_rows = dh_nmos_rows
	                    elif j_prefix == 'ach2':
	                        if mh_order == 'P_FIRST':
	                            target_rows = nmos_rows + dh_nmos_rows
	                        else : 
	                            target_rows = pmos_rows + dh_pmos_rows
	                    elif j_prefix == 'ach3p1':
	                        if mh_order == 'P_FIRST':
	                            target_rows = nmos_rows + pmos_rows + dh_nmos_rows
	                        else : 
	                            target_rows = nmos_rows + pmos_rows + dh_pmos_rows
	                        if MAX_TRACK % 2 == 1:
	                            target_rows = target_rows + middle_row
	                    elif j_prefix == 'ach3p2':
	                        if mh_order == 'P_FIRST':
	                            target_rows = nmos_rows + dh_pmos_rows + dh_nmos_rows
	                        else : 
	                            target_rows = pmos_rows + dh_pmos_rows + dh_nmos_rows
	                        if MAX_TRACK % 2 == 1:
	                            target_rows = target_rows + dh_middle_row
	                    elif j_prefix == 'ach4':
	                        target_rows = rows + dh_rows
	                    #print (net,j,key,h)
	                    #print (net,j,target_rows)
	                    c_mar_row[net,j] = model.addVars(target_rows, vtype=gp.GRB.BINARY, name=f"c_mar_row_{net}_{j}_r")
	                    model.addConstr(gp.quicksum(c_mar_row[net,j][r] for r in target_rows) <= len(target_rows)*indicator_i_vars[net,j],name=f'row_selection_on_off_rule1_{net}_{j}')
	                    #model.addConstr(gp.quicksum(c_mar_row[net,j][r] for r in target_rows) >= indicator_i_vars[net,j],name=f'row_selection_on_off_rule3_{net}_{j}')                
	                    model.addConstr(gp.quicksum(c_mar_row[net,j][r] for r in target_rows) <= len(target_rows)*io_detector,name=f'row_selection_on_off_rule2_{net}_{j}')
	                    model.addConstr(gp.quicksum(c_mar_row[net,j][r] for r in target_rows) >= (indicator_i_vars[net,j] + io_detector - 1),name=f'row_selection_on_off_rule3_{net}_{j}')                
	                    for r in target_rows:
	                        case[net,j,r] = model.addVars(range(len(target_list)), vtype=gp.GRB.BINARY, name=f"c_mar_row_{net}_{j}_{r}_case")
	                        model.addConstr(gp.quicksum(case[net,j,r][n] for n in range(len(target_list))) <= c_mar_row[net,j][r],name=f'case_selection_on_off_rule1_{net}_{j}_{r}')
	                        model.addConstr(gp.quicksum(case[net,j,r][n] for n in range(len(target_list))) >= c_mar_row[net,j][r],name=f'case_selection_on_off_rule2_{net}_{j}_{r}')
	                        for n, l in enumerate(target_list):
	                            l_l = len(l)
	                            #print (net,j,r,n,l,l_l,M_MAR+2)
	                            for i,local_c in enumerate(l):
	                                if i == 0:
	                                    prefix = "left_edge"
	                                elif i == len(l) - 1:
	                                    prefix = "right_edge"
	                                else:
	                                    prefix = "real_metal"
	
	                                if i == 0 or i == l_l - 1:
	                                    if l_l == M_MAR + 2:
	                                        expr = t_n_c_r[net][local_c, r] + t_n_c_r[new_net_name][local_c, r]
	                                    else:
	                                        if (i == 0 and local_c == 0) or (i == len(l) - 1 and local_c == num_cols - 1):
	                                            expr = t_n_c_r[net][local_c, r]
	                                        else:
	                                            expr = t_n_c_r[net][local_c, r] + t_n_c_r[new_net_name][local_c, r]
	                                else:
	                                    expr = t_n_c_r[net][local_c, r]
	                                model.addConstr(case[net, j, r][n] <= expr,name=f"mar_constraint_{net}_{j}_{r}_{prefix}")
	
	        for edge in Edges_m0:
	            i, j = edge
	            #print (i,j)
	            j_prefix, j_num, h = j.split('_')[0], int(j.split('_')[1]), int(j.split('_')[2])
	            cal_c = (j_num - 1) // 3 # divisor = 3
	            if j_prefix == 'middle':
	                if h == 1:
	                    target_rows = [middle_row]
	                else :
	                    target_rows = [dh_middle_row]
	            elif j_prefix == 'pv':
	                if h == 1:
	                    target_rows = pmos_rows
	                else :
	                    target_rows = dh_pmos_rows
	            elif j_prefix == 'nv':
	                if h == 1:
	                    target_rows = nmos_rows
	                else :
	                    target_rows = dh_nmos_rows
	            #print (i,j,j_prefix,cal_c,h,target_rows)
	            for row in target_rows:
	                var_name = f"y_{net}_edge_{i}_{j}_{row}"
	                flow_var_name = f"f_{net}_edge_{i}_{j}_{row}"
	                y_n_c_r[net][i,j,row] = model.addVar(vtype=gp.GRB.BINARY, name=var_name)
	                f_n_c_r[net][i,j,row] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.CONTINUOUS, name=flow_var_name)
	                model.addConstr(y_n_c_r[net][i, j, row] <= sum_actives-1,f"global_zero_constraint_{net}_{i}_{j}_{row}")
	                model.addConstr((min_indicator[net]-bbox)-cal_c <= num_cols*(1 - y_n_c_r[net][i, j, row]), name=f"active_c_ge_min_indicator_min_bbox_{net}_{i}_{j}_{row}")
	                model.addConstr(cal_c-(max_bbox[net]+bbox) <= num_cols*(1 - y_n_c_r[net][i, j, row]), name=f"active_c_ge_max_bbox_min_bbox_{net}_{i}_{j}_{row}")
	                model.addConstr(f_n_c_r[net][i, j, row] <= cap * y_n_c_r[net][i, j, row], name=f'edge_flow_ub_{net}_{i}_{j}_{row}')
	                model.addConstr(f_n_c_r[net][i, j, row] >= -cap * y_n_c_r[net][i, j, row], name=f'edge_flow_lb_{net}_{i}_{j}_{row}')
	                # model.addConstr(flow_cap[net][i, j, row] <= cap * y_n_c_r[net][i, j, row], "flow_cap_lim1")
	                # model.addConstr(flow_cap[net][i, j, row] <= sum_actives-1, "flow_cap_lim2")
	                # model.addConstr(flow_cap[net][i, j, row] >= sum_actives-1 - cap * (1 - y_n_c_r[net][i, j, row]), "flow_cap_lim3")
	                # model.addConstr(flow_cap[net][i, j, row] >= 0, "flow_cap_lim4")
	                # model.addConstr(f_n_c_r[net][i, j, row] >= -flow_cap[net][i, j, row], "flow_lb")
	                # model.addConstr(f_n_c_r[net][i, j, row] <=  flow_cap[net][i, j, row], "flow_ub")
	
	        for edge in Edges_m1:
	            i, j = edge
	            j_prefix, j_num, h = j.split('_')[0], int(j.split('_')[1]), int(j.split('_')[2])
	            cal_c = (j_num - 1) // 3 # divisor = 3
	            if h == 1:
	                target_rows = upper_rows
	            elif h == 2:
	                target_rows = dh_upper_rows
	            if j.startswith('pv_') or j.startswith('nv_') or j.startswith('middle_'):
	                var_name = f"y_{net}_edge_via_enable_{i}_{j}"
	                flow_var_name = f"f_{net}_edge_via_enable_{i}_{j}"
	                y_n_c_r[net][i, j, 've'] = model.addVar(vtype=gp.GRB.BINARY, name=var_name)
	                model.addConstr(y_n_c_r[net][i, j, 've'] <= sum_actives-1,f"global_zero_constraint_{net}_{i}_{j}_ve")
	                model.addConstr((min_indicator[net]-bbox)-cal_c <= num_cols*(1 - y_n_c_r[net][i, j, 've']), name=f"active_c_ge_min_indicator_min_one_{net}_{i}_{j}_ve")
	                model.addConstr(cal_c-(max_bbox[net]+bbox) <= num_cols*(1 - y_n_c_r[net][i, j, 've']), name=f"active_c_ge_max_bbox_min_bbox_{net}_{i}_{j}_ve")
	                f_n_c_ur[net][i, j, 've'] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.CONTINUOUS, name=flow_var_name)
	                model.addConstr(f_n_c_ur[net][i, j, 've'] <= cap * y_n_c_r[net][i, j, 've'], name=f'edge_flow_ub_{net}_{i}_{j}_ve')
	                model.addConstr(f_n_c_ur[net][i, j, 've'] >= -cap * y_n_c_r[net][i, j, 've'],name=f'edge_flow_lb_{net}_{i}_{j}_ve')
	                # flow_cap2[net][i, j, 've'] = model.addVar(vtype=gp.GRB.INTEGER, name=f"flow_cap_{net}_edge")
	                # model.addConstr(flow_cap2[net][i, j, 've'] <= cap * y_n_c_r[net][i, j, 've'], "flow_cap_lim1")
	                # model.addConstr(flow_cap2[net][i, j, 've'] <= sum_actives-1, "flow_cap_lim2")
	                # model.addConstr(flow_cap2[net][i, j, 've'] >= sum_actives-1 - cap * (1 - y_n_c_r[net][i, j, 've']), "flow_cap_lim3")
	                # model.addConstr(flow_cap2[net][i, j, 've'] >= 0, "flow_cap_lim4")
	                # model.addConstr(f_n_c_ur[net][i, j, 've'] >= -flow_cap2[net][i, j, 've'], "flow_lb")
	                # model.addConstr(f_n_c_ur[net][i, j, 've'] <=  flow_cap2[net][i, j, 've'], "flow_ub")
	            else:
	                for row in target_rows:
	                    var_name = f"y_{net}_edge_{i}_{j}_r_{row}"
	                    flow_var_name = f"f_{net}_edge_{i}_{j}_r_{row}"
	                    y_n_c_r[net][i,j,row] = model.addVar(vtype=gp.GRB.BINARY, name=var_name)
	                    model.addConstr(y_n_c_r[net][i, j, row] <= sum_actives-1,f"global_zero_constraint_{net}_{i}_{j}_{row}")
	                    model.addConstr((min_indicator[net]-bbox)-cal_c <= num_cols*(1 - y_n_c_r[net][i, j, row]), name=f"active_c_ge_min_indicator_min_one_{net}_{i}_{j}_{row}")
	                    model.addConstr(cal_c-(max_bbox[net]+bbox) <= num_cols*(1 - y_n_c_r[net][i, j, row]), name=f"active_c_ge_max_bbox_min_bbox_{net}_{i}_{j}_{row}")
	                    f_n_c_ur[net][i,j,row] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.CONTINUOUS, name=flow_var_name)
	                    model.addConstr(f_n_c_ur[net][i, j, row] <= cap * y_n_c_r[net][i, j, row],name=f'edge_flow_ub_{net}_{i}_{j}_{row}')
	                    model.addConstr(f_n_c_ur[net][i, j, row] >= -cap * y_n_c_r[net][i, j, row],name=f'edge_flow_lb_{net}_{i}_{j}_{row}')
	                    # flow_cap2[net][i, j, row] = model.addVar(vtype=gp.GRB.INTEGER, name=f"flow_cap_{net}_edge")
	                    # model.addConstr(flow_cap2[net][i, j, row] <= cap * y_n_c_r[net][i, j, row], "flow_cap_lim1")
	                    # model.addConstr(flow_cap2[net][i, j, row] <= sum_actives-1, "flow_cap_lim2")
	                    # model.addConstr(flow_cap2[net][i, j, row] >= sum_actives-1 - cap * (1 - y_n_c_r[net][i, j, row]), "flow_cap_lim3")
	                    # model.addConstr(flow_cap2[net][i, j, row] >= 0, "flow_cap_lim4")
	                    # model.addConstr(f_n_c_ur[net][i, j, row] >= -flow_cap2[net][i, j, row], "flow_lb")
	                    # model.addConstr(f_n_c_ur[net][i, j, row] <=  flow_cap2[net][i, j, row], "flow_ub")
	
	        for edge in Edges_vh:
	            i, j = edge
	            #print (net,i,j,cap)
	            j_prefix, j_num, h = j.split('_')[0], int(j.split('_')[1]), int(j.split('_')[2])
	            cal_c = (j_num - 1) // 3 # divisor = 3
	            var_name = f"y_{net}_height_connector_{i}_{j}_vh"
	            flow_var_name = f"f_{net}_height_connector_{i}_{j}_vh"
	            y_n_c_r[net][i, j, 'vh'] = model.addVar(vtype=gp.GRB.BINARY, name=var_name)
	            model.addConstr(y_n_c_r[net][i, j, 'vh'] <= sum_actives-1,f"global_zero_constraint_{net}_{i}_{j}_vh")
	            model.addConstr((min_indicator[net]-bbox)-cal_c <= num_cols*(1 - y_n_c_r[net][i, j, 'vh']), name=f"active_c_ge_min_indicator_min_one_{net}_{i}_{j}_vh")
	            model.addConstr(cal_c-(max_bbox[net]+bbox) <= num_cols*(1 - y_n_c_r[net][i, j, 'vh']), name=f"active_c_ge_max_bbox_min_bbox_{net}_{i}_{j}_vh")
	            f_n_c_r[net][i, j, 'vh'] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.CONTINUOUS, name=flow_var_name)
	            model.addConstr(f_n_c_r[net][i, j, 'vh'] <= cap * y_n_c_r[net][i, j, 'vh'], name=f'edge_flow_ub_{net}_{i}_{j}_ve')
	            model.addConstr(f_n_c_r[net][i, j, 'vh'] >= -cap * y_n_c_r[net][i, j, 'vh'],name=f'edge_flow_lb_{net}_{i}_{j}_ve')
	
	        #print("Big : ",big)
	        for m1 in m1_columns:
	            v_i, h = int(m1.split('_')[1]), int(m1.split('_')[2])
	            #print (m1,v_i,h)
	            v_index = via_positions.index(v_i)
	            if h == 2 :
	                model.addConstr(y_n_c_r[net][f"m1_{v_i}_{h-1}", m1, f"vh"] == vh_n_v[net][v_index], name=f"vh_enable_{net}_{v_i}")
	                model.addConstr(1 - vh_n_v[net][v_index] >= v_n_v[net][h-1,v_index], name=f"m1_cross_check_1_{net}_{v_i}")
	                model.addConstr(1 - vh_n_v[net][v_index] >= v_n_v[net][h,v_index], name=f"m1_cross_check_2_{net}_{v_i}")
	            model.addConstr(y_n_c_r[net][m1, f"pv_{v_i}_{h}", f"ve"] <= vh_n_v[net][v_index]+v_n_v[net][h,v_index], name=f"via_enable_{net}_pv_{v_i}_{h}")
	            model.addConstr(y_n_c_r[net][m1, f"nv_{v_i}_{h}", f"ve"] <= vh_n_v[net][v_index]+v_n_v[net][h,v_index], name=f"via_enable_{net}_nv_{v_i}_{h}")
	            if MAX_TRACK % 2 == 1:
	                model.addConstr(y_n_c_r[net][m1, f"middle_{v_i}_{h}", f"ve"] <= vh_n_v[net][v_index]+v_n_v[net][h,v_index], name=f"via_enable_{net}_middle_{v_i}_{h}")
	        
	        # edge -> track cost
	        for i, j in Edges:
	            #print (i,j)
	            i_prefix, i_num = i.split('_')[0], int(i.split('_')[1])
	            j_prefix, j_num = j.split('_')[0], int(j.split('_')[1])
	            if not j_prefix.startswith('ac') and j_prefix != 'pp' and j_prefix != 'nn':
	                # flow -> row selection -> track cost
	                if i_num > j_num:
	                    i_num, j_num = j_num, i_num
	                    i_prefix, j_prefix = j_prefix, i_prefix
	                i_index = i_num // 3 - 1
	                if i_num not in column_positions[1]:  # only for 2 to 3
	                    i_diff_1 = 3*(i_index + 2)-i_num
	                    i_diff_2 = i_num-3*(i_index+1)
	                    if i_diff_1 <= i_diff_2 and i_diff_1 <= V_OVL:
	                        i_index = i_num // 3
	                        #print (i,i_num,i_index,iasdsa_index)
	                if j_num in column_positions[1]:
	                    j_index = j_num//3-1  # only for 2 to 3
	                #elif j_prefix == 'pv' or j_prefix == 'nv' or j_prefix == 'm1':
	                else: # only for 2 to 3
	                    j_index = min(len(columns),(j_num+2)//3)-1
	                    #print (j,j_num,j_index,len(columns),columns)
	                    j_diff_1 = j_num-3*j_index
	                    j_diff_2 = 3*(j_index+1)-j_num
	                    if j_diff_1 <= j_diff_2 and j_diff_1 <= V_OVL:
	                        j_index = j_index - 1
	                        #print (j,j_num,j_index,j_index_As)
	                
	                if i_prefix != 'm1':
	                    h = int(i.split('_')[2])
	                    if j_prefix == 'middle':
	                        if h == 1:
	                            target_rows = [middle_row]
	                        elif h == 2:
	                            target_rows = [dh_middle_row]
	                    elif j_prefix == 'pv':
	                        if h == 1:
	                            target_rows = pmos_rows
	                        elif h == 2:
	                            target_rows = dh_pmos_rows
	                    elif j_prefix == 'nv':
	                        if h == 1:
	                            target_rows = nmos_rows
	                        elif h == 2:
	                            target_rows = dh_nmos_rows
	                    for r in target_rows:
	                        #if j_prefix == 'pp' or j_prefix == 'nn' or j_prefix == 'ac':
	                        #    model.addConstr(y_n_c_r[net][i,j,r] == c_mar_row[net,j][r],name=f"link_c_mar_row_to_y_n_c_r_{net}_{i}_{j}_{r}")
	                        for c in range(i_index, j_index+1):
	                            model.addConstr(
	                                t_n_c_r[net][c, r] >= y_n_c_r[net][i, j, r],
	                                name=f"t_activation_{net}_{i}_{j}_{c}_{r}"
	                            )
	                        if i_index - 1 >= 0:  # Ensure valid index
	                            model.addConstr(y_n_c_r[net][i, j, r] <= t_n_c_r[net][i_index - 1, r] + t_n_c_r[new_net_name][i_index - 1, r],name=f"logical_constraint_{net}_{i}_{j}_i_index_minus_1_{r}")
	                        if j_index+1 <= len(columns) - 1:
	                            model.addConstr(y_n_c_r[net][i, j, r] <= t_n_c_r[net][j_index+1, r] + t_n_c_r[new_net_name][j_index+1, r],name=f"logical_constraint_{net}_{i}_{j}_j_index_{r}")      
	                else:
	                    if j_prefix == 'm1':
	                        hj = int(j.split('_')[2])
	                        h = int(i.split('_')[2])
	                        if h == hj :
	                            if h == 1:
	                                target_rows = upper_rows
	                            elif h == 2:
	                                target_rows = dh_upper_rows
	                            for r in target_rows:
	                                if i_index != j_index:
	                                    # Add constraints for all `c` in the range [i_index, j_index]
	                                    for c in range(i_index, j_index+1):
	                                        model.addConstr(
	                                            ut_n_c_r[net][c, r] >= y_n_c_r[net][i, j, r],
	                                            name=f"t_activation_{net}_{i}_{j}_{c}_{r}"
	                                        )
	                                    if i_index - 1 >= 0:  # Ensure valid index
	                                        model.addConstr(
	                                            y_n_c_r[net][i, j, r] <= ut_n_c_r[net][i_index - 1, r] + ut_n_c_r[new_net_name][i_index - 1, r],
	                                            name=f"logical_constraint_{net}_{i}_{j}_i_index_minus_2_{r}"
	                                        )
	                                    if j_index+1 <= len(columns) - 1:
	                                        model.addConstr(
	                                            y_n_c_r[net][i, j, r] <= ut_n_c_r[net][j_index+1, r] + ut_n_c_r[new_net_name][j_index+1, r],
	                                            name=f"logical_constraint_{net}_{i}_{j}_j_index_{r}"
	                                        )
	                   
	        #print (net,cap)
	        for pos_i in sorted_connection_points:
	            #print (pos_i)
	            if pos_i.startswith('ach'):
	                i_prefix, i_num = pos_i.split('_')[0], int(pos_i.split('_')[1])
	                h = 2
	            else:    
	                i_prefix, i_num, h = pos_i.split('_')[0], int(pos_i.split('_')[1]), int(pos_i.split('_')[2])
	            if i_prefix == 'middle':
	                if h == 1:
	                    target_rows = [middle_row]
	                elif h == 2:
	                    target_rows = [dh_middle_row]
	            elif i_prefix == 'pv':
	                if h == 1:
	                    target_rows = pmos_rows
	                elif h == 2:
	                    target_rows = dh_pmos_rows
	            elif i_prefix == 'nv':
	                if h == 1:
	                    target_rows = nmos_rows
	                elif h == 2:
	                    target_rows = dh_nmos_rows
	            elif i_prefix == 'm1':
	                if h == 1:
	                    target_rows = upper_rows
	                elif h == 2:
	                    target_rows = dh_upper_rows
	            #print (pos_i,i_prefix,i_num)
	            if i_prefix == 'm1':
	                #rint (pos_i,target_rows)
	                if h == 1:
	                    inflow = gp.quicksum(f_n_c_ur[net][j, k, r] for j, k in Edges_m1 if k == pos_i and j.startswith('m1') for r in target_rows)
	                    outflow = gp.quicksum(f_n_c_r[net][j, k, 'vh'] for j, k in Edges_vh if j == pos_i) + gp.quicksum(f_n_c_ur[net][j, k, r] for j, k in Edges_m1 if j == pos_i and k.startswith('m1') for r in target_rows) + gp.quicksum(f_n_c_ur[net][j, k, 've'] for j, k in Edges_m1 if j == pos_i and not k.startswith('m1'))
	                if h == 2 :
	                    inflow = gp.quicksum(f_n_c_r[net][j, k, 'vh'] for j, k in Edges_vh if k == pos_i) + gp.quicksum(f_n_c_ur[net][j, k, r] for j, k in Edges_m1 if k == pos_i and j.startswith('m1') for r in target_rows)
	                    outflow = gp.quicksum(f_n_c_ur[net][j, k, r] for j, k in Edges_m1 if j == pos_i and k.startswith('m1') for r in target_rows) + gp.quicksum(f_n_c_ur[net][j, k, 've'] for j, k in Edges_m1 if j == pos_i and not k.startswith('m1'))
	            elif i_prefix == 'pv' or i_prefix == 'nv' or i_prefix == 'middle':
	                #print (pos_i,target_rows)
	                if i_num in column_positions[1]:
	                    outflow = gp.quicksum(f_n_c_r[net][j, k, r] for j, k in Edges_m0 if j == pos_i for r in target_rows) + gp.quicksum(f_n_c_r[net][j, k, 'co'] for j, k in Edges_net if j == pos_i)
	                    if i_num in via_positions :
	                        inflow = gp.quicksum(f_n_c_r[net][j, k, r] for j, k in Edges_m0 if k == pos_i for r in target_rows) + gp.quicksum(f_n_c_ur[net][j, k, 've'] for j, k in Edges_m1 if k == pos_i)
	                    else :
	                        inflow = gp.quicksum(f_n_c_r[net][j, k, r] for j, k in Edges_m0 if k == pos_i for r in target_rows)
	                else :
	                    inflow = gp.quicksum(f_n_c_r[net][j, k, r] for j, k in Edges_m0 if k == pos_i for r in target_rows) + gp.quicksum(f_n_c_ur[net][j, k, 've'] for j, k in Edges_m1 if k == pos_i)
	                    outflow = gp.quicksum(f_n_c_r[net][j, k, r] for j, k in Edges_m0 if j == pos_i for r in target_rows)
	            else :
	                inflow = gp.quicksum(f_n_c_r[net][j, k, 'co'] for j, k in Edges_net if k == pos_i)
	                outflow = 0
	
	            net_flow[net, pos_i] = inflow - outflow
	            # Introduce auxiliary variable cap_i
	            #cap_i[net, pos_i] = model.addVar(vtype=gp.GRB.INTEGER, lb=-cap, ub=cap, name=f"cap_{net}_{pos_i}")
	            # Combine root node and non-root constraints
	            # If is_root_node[net, pos_i] is True -> cap_i = 1 - sum_actives
	            # If is_root_node[net, pos_i] is False -> cap_i = 1 or -1
	            if pos_i in wo_via_points:
	                #s_i[net, pos_i] = model.addVar(vtype=gp.GRB.BINARY, name=f"s_{net}_{pos_i}")
	                #model.addConstr(s_i[net, pos_i]<=indicator_i_vars[net, pos_i],name=f"binary_on_off_{net}_{pos_i}")
	                model.addGenConstrIndicator(
	                    is_root_node[net, pos_i], True,
	                    #cap_i[net, pos_i] == gp.LinExpr(1.0) - sum_actives,
	                    ##cap_i[net, pos_i] == 1 - sum_actives,
	                    net_flow[net, pos_i] == 1 - sum_actives,
	                    #cap_i[net, pos_i] == -1,
	                    name=f"t_definition_root_{net}_{pos_i}"
	                )
	                model.addGenConstrIndicator(
	                    is_root_node[net, pos_i], False,
	                    #cap_i[net, pos_i] == -indicator_i_vars[net, pos_i] + 2 * s_i[net, pos_i],
	                    ##cap_i[net, pos_i] == indicator_i_vars[net, pos_i],
	                    net_flow[net, pos_i] == indicator_i_vars[net, pos_i],
	                    name=f"t_definition_non_root_{net}_{pos_i}"
	                )
	            else:
	                #print(pos_i)
	                ##model.addConstr(cap_i[net, pos_i] == 0, name=f"middle_node_{net}_{pos_i}")
	                model.addConstr(net_flow[net, pos_i] == 0, name=f"middle_node_{net}_{pos_i}")
	            #model.addConstr(
	            #    net_flow[net, pos_i] == cap_i[net, pos_i],
	            #    name=f"flow_conservation_{net}_{pos_i}"
	            #)

if routing_switch == 'on':
	# Prevent different nets from using the same via position
	for v in via_indices:
	    #model.addConstr(gp.quicksum(vh_n_v[net][v] for net in total_nets if net not in power_net) <= 1,name=f"vh_conflict_{v}")
	    for h in height:
	        model.addConstr(gp.quicksum(v_n_v[net][h,v] + vh_n_v[net][v] for net in total_nets if net not in power_net) <= 1,name=f"via_conflict_{h}_{v}")
	
	# Prevent different nets from using the same row selection
	# Prevent consecutive row usage
	for edge in Edges_m0:
	    i, j = edge
	    j_prefix, j_num, h = j.split('_')[0], int(j.split('_')[1]), int(j.split('_')[2])
	    if j_prefix == 'middle':
	        if h == 1:
	            target_rows = [middle_row]
	        elif h == 2:
	            target_rows = [dh_middle_row]
	    elif j_prefix == 'pv':
	        if h == 1:
	            target_rows = pmos_rows
	        elif h == 2:
	            target_rows = dh_pmos_rows
	    elif j_prefix == 'nv':
	        if h == 1:
	            target_rows = nmos_rows
	        elif h == 2:
	            target_rows = dh_nmos_rows
	    for r in target_rows:
	        model.addConstr(gp.quicksum(y_n_c_r[net][i,j,r] for net in total_nets if net not in power_net)<= 1,name=f"row_selection_conflict_{i}_{j}_{r}")
	    for net in total_nets:
	        if net not in power_net and len(target_rows)>1:
	            consecutive = 2
	            for r_start in range(len(target_rows) - consecutive + 1):
	                con_r = target_rows[r_start : r_start + consecutive]
	                #print(i,j,net,r_start,con_r)
	                model.addConstr(gp.quicksum(y_n_c_r[net][i,j,r] for r in con_r) <= 1,name=f"consecutive_row_usage_conflict_for_one_net_{net}_{i}_{j}")
	
	for edge in Edges_m1:
	    i, j = edge
	    j_prefix, j_num, h = j.split('_')[0], int(j.split('_')[1]), int(j.split('_')[2])
	    if j_prefix == 'm1':
	        if h == 1:
	            target_rows = upper_rows
	        elif h == 2:
	            target_rows = dh_upper_rows
	    if not j.startswith('pv_') and j.startswith('nv_') and j.startswith('middle_'):
	        for r in target_rows:
	            model.addConstr(gp.quicksum(y_n_c_r[net][i,j,r] for net in total_nets if net not in power_net)<= 1,name=f"row_selection_conflict_{i}_{j}_{r}")
	
	# Cell-Flex
	# horizontal pin separation -> horizontal pin extendability
	signal_nets = [net for net in io_pins if net not in power_net]
	pin_interruption = 2
	pin_extend_reward={}
	one_pin_net_binary={}
	cond = {}
	M = 20
	search_columns = [c for c in gate_cols[1] if 1 <= c and c <= len(columns)-2]
	for h in height:
	    if h == 1:
	        target_rows = rows
	    if h == 2:
	        target_rows = dh_rows
	    for c in search_columns:
	        extendability = model.addVar(vtype=gp.GRB.BINARY, name=f"l_e_{h}_{c}")
	        neighbor_cols = [c + dc for dc in range(-pin_interruption, pin_interruption+1) if 0 <= c + dc < len(columns)]
	        #print (c,neighbor_cols)
	        pin_extend_reward[h,c] = model.addVar(vtype=gp.GRB.INTEGER, name=f"p_e_r_{h}_{c}")
	        cond[h,c]={}
	        one_pin_net_binary[h,c]={}
	        for r in target_rows:
	            row_metal = gp.quicksum(t_n_c_r[net][ni,r] for net in total_nets if net not in power_net for ni in neighbor_cols)
	            for s_n in signal_nets:
	                cond[h,c][r, s_n] = model.addVar(vtype=gp.GRB.BINARY,name=f"{h}_cond_col{c}_row{r}_net{s_n}")
	                pin_metal = gp.quicksum(t_n_c_r[s_n][ni,r] for ni in neighbor_cols)
	                one_pin_net_binary[h,c][s_n] = model.addVar(vtype=gp.GRB.BINARY, name=f"one_pin_net_bin_{h}_{c}_{s_n}")
	                pin_is_there = model.addVar(vtype=GRB.BINARY, name=f"pin_is_there_{r}_{s_n}")
	                
	                model.addConstr(sum_actives_vars[s_n] <= 1 + M * (1-one_pin_net_binary[h,c][s_n]),name=f"via_used_binary_upper")
	                model.addConstr(sum_actives_vars[s_n] >= 2 - M * one_pin_net_binary[h,c][s_n],name=f"via_used_binary_lower")
	                model.addConstr(cond[h,c][r,s_n] <= one_pin_net_binary[h,c][s_n],name=f"cond_via_{h}_{c}_{r}_{s_n}")
	
	                model.addConstr(cond[h,c][r,s_n] <= pin_metal,name=f"cond_pinmetal_{h}_{c}_{r}_{s_n}")
	                model.addConstr(pin_is_there <= pin_metal,name=f"pin_is_there1_pinmetal_{h}_{c}_{r}_{s_n}")
	                model.addConstr(pin_is_there >= pin_metal/len(neighbor_cols),name=f"pin_is_there2_pinmetal_{h}_{c}_{r}_{s_n}")
	
	                model.addConstr(row_metal - pin_metal <= M*(1-cond[h,c][r,s_n]),name=f"cond_upper_{h}_{c}_{r}_{s_n}")
	                model.addConstr(row_metal - pin_metal >= one_pin_net_binary[h,c][s_n] + pin_is_there - 1 - cond[h,c][r,s_n],name=f"cond_lower_{h}_{c}_{r}_{s_n}")
	
	        model.addConstr(pin_extend_reward[h,c]==gp.quicksum(cond[h,c][r,s_n] for r in target_rows for s_n in signal_nets),name=f"reward_make_for_{c}")
	
	# vertical pin separation
	z_dict = {}  # dictionary - z_{c,net1,net2,r1,r2}
	for h in height:
	    if h == 1:
	        target_rows = rows
	    if h == 2:
	        target_rows = dh_rows
	    for c in gate_cols[h][:-1]:
	        pos_a = f"ac_{3 + 3 * c}_{h}"
	        pos_a_next = f"ac_{3 + 3 * (c+2)}_{h}"
	        for net1 in signal_nets:
	            for net2 in signal_nets:
	                if net1 == net2:
	                    continue
	                for r1 in target_rows:
	                    for r2 in target_rows:
	                        if abs(r1-r2) >= 3:
	                            z_dict[(c,net1,net2,r1,r2)] = model.addVar(vtype=gp.GRB.BINARY,name=f"z_{c}_{net1}_{net2}_{r1}_{r2}")
	                            # 1) z <= c_mar_row[net1, j_c][r1]
	                            model.addConstr(z_dict[(c,net1,net2,r1,r2)] <= c_mar_row[net1, pos_a][r1], name=f"z_le_net1_{c}_{net1}_{r1}")
	                            # 2) z <= c_mar_row[net2, j_c1][r2]
	                            model.addConstr(z_dict[(c,net1,net2,r1,r2)] <= c_mar_row[net2, pos_a_next][r2], name=f"z_le_net2_{c}_{net2}_{r2}")
	                            # 3) z >= c_mar_row[net1, j_c][r1] + c_mar_row[net2, j_c1][r2] - 1
	                            model.addConstr(z_dict[(c,net1,net2,r1,r2)] >= c_mar_row[net1, pos_a][r1] + c_mar_row[net2, pos_a_next][r2] - 1, name=f"z_ge_{c}_{net1}_{net2}_{r1}_{r2}")
	
	
	# OBS misalign penalty
	obs_misalign_penalty={} # OBS is in the row
	if len(height) > 1:
	    target_upper_rows = upper_rows+dh_upper_rows
	else :
	    target_upper_rows = upper_rows
	print (target_upper_rows)
	for r in target_upper_rows:
	    obs_misalign_penalty[r] = model.addVar(vtype=gp.GRB.BINARY, name=f"o_m_p_{r}")
	    model.addConstr(obs_misalign_penalty[r] <= gp.quicksum(ut_n_c_r[net][c,r] for net in total_nets if net not in io_pins for c in columns) ,name=f"o_m_p_constr1_{r}")
	    for net in total_nets:
	        if net not in io_pins:
	            for c in columns:
	                model.addConstr(obs_misalign_penalty[r] >= ut_n_c_r[net][c,r] ,name=f"o_m_p_constr2_{net}_{c}_{r}")
	
	# Track cost constraints per row
	for c in columns:
	    for r in rows+dh_rows:
	        model.addConstr(
	            t_c_r[c, r] == gp.quicksum(t_n_c_r[net][c, r] for net in total_nets if net not in power_net),
	            name=f"track_cost_{c}_{r}"
	        )
	        model.addConstr(
	            t_c_r[c, r] + t_n_c_r[new_net_name][c, r] <= 1,
	            name=f"max_track_{c}_{r}"
	        )
	    for r in upper_rows+dh_upper_rows:
	        model.addConstr(
	            ut_c_r[c, r] == gp.quicksum(ut_n_c_r[net][c, r] for net in total_nets if net not in power_net),
	            #ut_c_r[c, r] == gp.quicksum(ut_n_c_r[net][c, r] for net in new_nets),
	            name=f"uppertrack_cost_{c}_{r}"
	        )
	        model.addConstr(
	            ut_c_r[c, r] + ut_n_c_r[new_net_name][c, r]  <= 1,
	            name=f"max_uppertrack_{c}_{r}"
	        )
	
	# Total track cost per column
	for h in height:
	    for c in columns:
	        if h == 1:
	            model.addConstr(
	                ut_c[h,c] == gp.quicksum(ut_c_r[c, r] for r in upper_rows),
	                name=f"uppertrack_cost_{h}_{c}"
	            )
	            model.addConstr(
	                t_c[h,c] == gp.quicksum(t_c_r[c, r] for r in rows),
	                name=f"track_cost_{h}_{c}"
	            )
	        elif h == 2:
	            model.addConstr(
	                ut_c[h,c] == gp.quicksum(ut_c_r[c, r] for r in dh_upper_rows),
	                name=f"uppertrack_cost_{h}_{c}"
	            )
	            model.addConstr(
	                t_c[h,c] == gp.quicksum(t_c_r[c, r] for r in dh_rows),
	                name=f"track_cost_{h}_{c}"
	            )
	        model.addConstr(
	            t_c[h,c] <= MAX_TRACK,
	            name=f"max_track_{h}_{c}"
	        )
	
	# Objective function
	via_cost = 60
	via_pdn_cost = 100
	vh_cost = 90
	vh_pdn_cost = 110
	lowertrack_cost = 3
	uppertrack_cost = 6
	eol_cost = 1
	total_via_cost = vh_cost * gp.quicksum(vh_n_v[net][v]  for net in total_nets if net not in power_net for v in via_indices if 4*(v+1) % 3 !=0) + via_cost * gp.quicksum(v_n_v[net][h,v]  for net in total_nets if net not in power_net for h in height for v in via_indices if 4*(v+1) % 3 !=0) + vh_pdn_cost * gp.quicksum(vh_n_v[net][v]  for net in total_nets if net not in power_net for v in via_indices if 4*(v+1) % 3 ==0) + via_pdn_cost * gp.quicksum(v_n_v[net][h,v]  for net in total_nets if net not in power_net for h in height for v in via_indices if 4*(v+1) % 3 ==0)
	#total_via_cost = vh_cost * gp.quicksum(vh_n_v[net][v]  for net in total_nets if net not in power_net for v in via_indices) + via_cost * gp.quicksum(v_n_v[net][h,v]  for net in total_nets if net not in power_net for h in height for v in via_indices)
	#total_via_cost = via_cost * gp.quicksum(v_n_v[net][v] for net in new_nets for v in valid_via_indices[net])
	total_track_cost = lowertrack_cost * gp.quicksum(t_c[h,c] for h in height for c in columns)
	total_uppertrack_cost = 2 * uppertrack_cost * gp.quicksum(ut_c[h,c] for h in height for c in columns)
	total_eol_cost = eol_cost * gp.quicksum(t_n_c_r[new_net_name][c,r] for c in columns for r in rows+dh_rows)
	total_uppertrack_eol_cost = eol_cost * uppertrack_cost * gp.quicksum(ut_n_c_r[new_net_name][c,r] for c in columns for r in upper_rows+dh_upper_rows)
	#model.setObjective(total_track_cost + total_via_cost + total_uppertrack_cost + total_eol_cost + total_uppertrack_eol_cost, GRB.MINIMIZE)
	
	# Cell-Flex
	o_m_p_cost = 100
	obs_penalty_1 = o_m_p_cost * gp.quicksum(obs_misalign_penalty[r] for r in upper_rows)
	# Reward
	# reward
	p_e_cost = 1
	pin_extendability = p_e_cost*gp.quicksum(pin_extend_reward[h,c] for h in height for c in search_columns)
	p_s_cost = 1
	pin_separation = p_s_cost*gp.quicksum(z_dict[idx] for idx in z_dict)
	# Final MINIMIZE FUNCTION
	#model.setObjective(total_track_cost + total_via_cost + total_uppertrack_cost + total_eol_cost + total_uppertrack_eol_cost, GRB.MINIMIZE)
	model.setObjective(total_track_cost + total_via_cost + total_uppertrack_cost + total_eol_cost + total_uppertrack_eol_cost + obs_penalty_1 - pin_extendability - pin_separation ,gp.GRB.MINIMIZE)
	#model.setObjective(total_track_cost + total_via_cost + total_uppertrack_cost + total_eol_cost + total_uppertrack_eol_cost + obs_penalty_1 - pin_extendability,gp.GRB.MINIMIZE)
	#model.setObjective(total_track_cost + total_via_cost + total_uppertrack_cost + total_eol_cost + total_uppertrack_eol_cost,gp.GRB.MINIMIZE)

if routing_switch == 'off':
# objective function for only placement
    model.setObjective(
        gp.quicksum(flow_estimator[h,c] for h in height for c in gate_cols),
        GRB.MINIMIZE
    )

# Optimize model
start_time = time.perf_counter()
model.optimize()
end_time = time.perf_counter()

if model.status == GRB.OPTIMAL:
    pr("Optimal solution found.")
    total_cost = model.objVal
    best_via_locations = {
        net: [(h,via_positions[v]) for h in height for v in via_indices if v_n_v[net][h,v].X > 0.5] for net in total_nets if net not in power_net
        #net: [via_positions[v] for v in valid_via_indices[net] if v_n_v[net][v].X > 0.5] for net in new_nets
    }
    best_vh_locations = {
        net: [via_positions[v] for v in via_indices if vh_n_v[net][v].X > 0.5] for net in total_nets if net not in power_net
        #net: [via_positions[v] for v in valid_via_indices[net] if v_n_v[net][v].X > 0.5] for net in new_nets
    }
    eol = {}
    for h in height:
        for c in columns:
            eol[h,c]=0
            if h == 1:
                for r in rows:
                    eol[h,c] = eol[h,c] + t_n_c_r[new_net_name][c,r].X
            elif h == 2:
                for r in dh_rows:
                    eol[h,c] = eol[h,c] + t_n_c_r[new_net_name][c,r].X
    #print (eol)
    column_track_costs={}
    for h in height:
        for c in columns:
            column_track_costs[h,column_positions[h][c]] = (t_c[h,c].X+eol[h,c])
    #print (column_track_costs)
    sorted_column_positions = sorted(column_track_costs.keys())
    #print (sorted_column_positions)
    best_track_cost_list = {}
    for h, c in sorted_column_positions:
        if h not in best_track_cost_list:
            best_track_cost_list[h] = []
        best_track_cost_list[h].append(int(column_track_costs[(h, c)]))
    
    for i,t in enumerate(top_trans):
        for h in height:
            for c in gate_cols[h]:
                for o in [0,1]:
                    if c_top[(i,h,c,o)].X > 0.5:
                        print(f"Top: {t[0]} placed at height {h} column {c}, orientation={o}")

    for j,t in enumerate(bot_trans):
        for h in height:
            for c in gate_cols[h]:
                for o in [0,1]:
                    if c_bot[(j,h,c,o)].X > 0.5:
                        print(f"Bottom: {t[0]} placed at height {h} column {c}, orientation={o}")

    #for c,z in misalign_c.items():
    #    print(f"Column {c} misalignment: {z.X}")

    pmos_columns = {h: [None] * num_cols for h in height}
    nmos_columns = {h: [None] * num_cols for h in height}

    for h in height:
        for c in range(num_cols):
            for net in unique_pmos_nets:
                if pmos_net[(net, h, c)].X > 0.5:
                    pmos_columns[h][c] = net  # Store net at height h, column c
                    #print ("P",net,h,c)
            for net in unique_nmos_nets:
                if nmos_net[(net, h, c)].X > 0.5:
                    nmos_columns[h][c] = net  # Store net at height h, column c
                    #print ("N",net,h,c)
    
    if mh_order == 'P_FIRST':
        for h in sorted(height, reverse=True):  # Reverse the height order
            if h % 2 == 1:
                pr("NMOS:", h, nmos_columns[h])
                pr("PMOS:", h, pmos_columns[h])
            else:
                pr("PMOS:", h, pmos_columns[h])
                pr("NMOS:", h, nmos_columns[h])
    
    if mh_order == 'N_FIRST':
        for h in sorted(height, reverse=True):  # Reverse the height order
            if h % 2 == 1:
                pr("PMOS:", h, pmos_columns[h])
                pr("NMOS:", h, nmos_columns[h])
            else:
                pr("NMOS:", h, nmos_columns[h])
                pr("PMOS:", h, pmos_columns[h])
    
    if routing_switch == 'on':
	    pr("\nt_n_c_r and ut_n_c_r values:")
	    for net in total_nets:
	        if net not in power_net:
	            pr(f"  Net {net}: Via positions {best_via_locations.get(net, [])}, {best_vh_locations.get(net, [])}")
	            for h in sorted(height, reverse=True):
	                if h == 1:
	                    for r in rows:
	                        c_t_c = {column_positions[h][c]: t_n_c_r[net][c, r].X for c in columns}
	                        s_c_p = sorted(c_t_c.keys())
	                        b_t_c_l = [int(round(c_t_c[c_pos])) for c_pos in s_c_p]
	                        pr(f"  Net {net}, H {h}, Row {r}: {b_t_c_l}")
	                elif h == 2:
	                    for r in dh_rows:
	                        c_t_c = {column_positions[h][c]: t_n_c_r[net][c, r].X for c in columns}
	                        s_c_p = sorted(c_t_c.keys())
	                        b_t_c_l = [int(round(c_t_c[c_pos])) for c_pos in s_c_p]
	                        pr(f"  Net {net}, H {h}, Row {r}: {b_t_c_l}")
	            for h in sorted(height, reverse=True):
	                if h == 1:
	                    for r in upper_rows:
	                        c_ut_c = {column_positions[h][c]: ut_n_c_r[net][c, r].X for c in columns}
	                        s_c_p = sorted(c_ut_c.keys())
	                        b_ut_c_l = [round(int(c_ut_c[c_pos])) for c_pos in s_c_p]
	                        pr(f"  Net {net}, H {h}, Row {r}: {b_ut_c_l}")
	                if h == 2:
	                    for r in dh_upper_rows:
	                        c_ut_c = {column_positions[h][c]: ut_n_c_r[net][c, r].X for c in columns}
	                        s_c_p = sorted(c_ut_c.keys())
	                        b_ut_c_l = [round(int(c_ut_c[c_pos])) for c_pos in s_c_p]
	                        pr(f"  Net {net}, H {h}, Row {r}: {b_ut_c_l}")
	    for h in sorted(height, reverse=True):
	        if h == 1:
	            target_rows = rows
	            target_upper_rows = upper_rows
	        elif h == 2:
	            target_rows = dh_rows
	            target_upper_rows = dh_upper_rows
	        for r in target_rows:
	            c_t_c = {column_positions[h][c]: t_n_c_r[new_net_name][c, r].X for c in columns}
	            s_c_p = sorted(c_t_c.keys())
	            b_t_c_l = [int(c_t_c[c_pos]) for c_pos in s_c_p]
	            pr(f"  Net {new_net_name}, Row {r}: {b_t_c_l}")
	        for r in target_upper_rows:
	            c_t_c = {column_positions[h][c]: ut_n_c_r[new_net_name][c, r].X for c in columns}
	            s_c_p = sorted(c_t_c.keys())
	            b_t_c_l = [int(c_t_c[c_pos]) for c_pos in s_c_p]
	            pr(f"  Net {new_net_name}, Row {r}: {b_t_c_l}")
	
	    # Results
	    pr(f"\nOptimal total cost: {total_cost}")
	    pr("Optimal Via positions:")
	    for net in total_nets:
	        if net not in power_net:
	            pr(f"  Net {net}: Via positions {best_via_locations.get(net, [])}, {best_vh_locations.get(net, [])}")
	    for h in sorted(best_track_cost_list.keys(), reverse=True):  # Reverse order
	        pr(f"{h} height Column Track Costs: {best_track_cost_list[h]}")
    
else:
    pr("No optimal solution found.")
pr ("Runtime : ",round(end_time-start_time,3))
