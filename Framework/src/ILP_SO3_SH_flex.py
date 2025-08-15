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
    return p.parse_args()

args = parse_args()
cell_name = args.cell or args.subckt
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
bbox = 0 # bounding box for routing
MAX_TRACK = 4 # TRACK DEFINE : 5,4,3,2
upper_rows=[7,6,5,4] # [7,6,5,4] m2 4track, [5,4,3] # m2 3track, [9,8,7,6,5] # m2 5track, [3,2] # m2 2track
metal_mar = 'Naive' # DR define : Strict or Naive or Min
via_overlap = 'Naive'
Architecture = '2to3'
zero_offset = 'on'
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
        _log = open(subckt_name, "w", encoding="utf-8", buffering=1)  # line-buffered
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

num_cols = 2 * (max(len(top_trans), len(bot_trans)) + dummy_col) + 1

################################## Edge generation based on num_cols
# Define columns and positions
column_positions = [3 + 3 * i for i in range(num_cols)]  # [3,6,9,12,15,18,21,24,27,30]
columns = list(range(len(column_positions)))  # Indices from 0 to 9
rows = list(range(MAX_TRACK-1, -1, -1))
#print (rows)
# split pmos and nmos track
pmos_rows = rows[:MAX_TRACK//2]
nmos_rows = rows[MAX_TRACK//2:]
# take care for odd track
if MAX_TRACK % 2 != 0:
    middle_row = rows[MAX_TRACK//2]
    nmos_rows.remove(middle_row)
total_rows = rows + upper_rows
via_positions = []
i = 0
while True:
    pos = int(offset + V_PITCH * (i+1))
    if pos > column_positions[-1]:
        break
    if pos >= 3 and pos <= column_positions[-1]:
        via_positions.append(pos)
    i += 1
via_indices = list(range(len(via_positions)))  # Indices of via positions
#print (f"VIA {via_positions} / {via_indices}")
print (column_positions)
print(via_positions)
col_via_pos = sorted(list(set(column_positions + via_positions)))
print (col_via_pos)
# nodes
pmos_via_columns = [f"pv_{v}" for v in col_via_pos]
nmos_via_columns = [f"nv_{v}" for v in col_via_pos]
middle_via_columns = [f"middle_{v}" for v in col_via_pos]
m1_columns = [f"m1_{v}" for v in via_positions]
pmos_net = [f"pp_{3 + 3 * c}" for c in columns]
nmos_net = [f"nn_{3 + 3 * c}" for c in columns]
aligned_net = [f"ac_{3 + 3 * c}" for c in columns]
if MAX_TRACK % 2 != 0:
    connection_points = aligned_net + pmos_via_columns + nmos_via_columns + pmos_net + nmos_net + m1_columns + middle_via_columns
else :
    connection_points = aligned_net + pmos_via_columns + nmos_via_columns + pmos_net + nmos_net + m1_columns
connection_points = sorted(set(connection_points))
sorted_connection_points = sorted(connection_points,key=lambda x: int(x.split('_')[1]))
wo_via_points = aligned_net + pmos_net + nmos_net

Edges = []
Edges_net = []
Edges_m0 = []
Edges_m1 = []

for col in column_positions:
    Edges_net.append((f"pv_{col}", f"pp_{col}"))
    Edges_net.append((f"pv_{col}", f"ac_{col}"))
    Edges_net.append((f"nv_{col}", f"nn_{col}"))
    Edges_net.append((f"nv_{col}", f"ac_{col}"))
    if MAX_TRACK % 2 == 1:
        Edges_net.append((f"middle_{col}", f"ac_{col}"))

Edges.extend(Edges_net)

# m0 movement edge
for i, v in enumerate(col_via_pos):
    #print (i,v)
    current_point = v
    if i < len(col_via_pos) - 1:
        next_point = col_via_pos[i+1]
        Edges_m0.append((f"pv_{current_point}", f"pv_{next_point}"))
        Edges_m0.append((f"nv_{current_point}", f"nv_{next_point}"))
        if MAX_TRACK % 2 == 1:
            Edges_m0.append((f"middle_{current_point}", f"middle_{next_point}"))

Edges.extend(Edges_m0)

# via to m1 & m2
for i, pos_i in enumerate(m1_columns):
    #print (i,pos_i)
    current_point = pos_i
    index_i = int(current_point.split('_')[1])
    Edges_m1.append((current_point, f"pv_{index_i}"))
    Edges_m1.append((current_point, f"nv_{index_i}"))
    if MAX_TRACK % 2 == 1:
        Edges_m1.append((current_point, f"middle_{index_i}"))
    if i < len(m1_columns) - 1:
        next_point = m1_columns[i + 1]
        Edges_m1.append((current_point, next_point))

Edges.extend(Edges_m1)

print(Edges)

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
#print(power_net)
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
gate_cols = [c for c in range(num_cols) if c % 2 == 1]
#print(gate_cols)
half_gate_cols = gate_cols[:(len(gate_cols) + 1) // 2]
#print(half_gate_cols)
after_half_gate_cols = [x for x in gate_cols if x not in half_gate_cols]
#print(after_half_gate_cols)

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
    for c in gate_cols:
        for o in [0,1]:
            c_top[(i,c,o)] = model.addVar(vtype=gp.GRB.BINARY, name=f"c_top_{name}_c{c}_o{o}")

# Binary variables for net placement across columns
pmos_net = {}
# Extract unique nets from t[1], t[2], and t[3] in top_trans
unique_pmos_nets = set(net for t in top_trans for net in [t[1], t[2], t[3]])
unique_pmos_nets.add("dummy")
#print (unique_pmos_nets)
for c in range(num_cols):
    for net in unique_pmos_nets:
        pmos_net[(net, c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"pmos_net_{net}_c{c}")
    #pmos_net[("dummy",c)]  = model.addVar(vtype=gp.GRB.BINARY, name=f"pmos_dummy_{net}_c{c}")

c_bot = {}
for j,t in enumerate(bot_trans):
    name,G,D,S,B,nfin = t
    for c in gate_cols:
        for o in [0,1]:
            c_bot[(j,c,o)] = model.addVar(vtype=gp.GRB.BINARY, name=f"c_bot_{name}_c{c}_o{o}")

# Binary variables for net placement across columns
nmos_net = {}
# Extract unique nets from t[1], t[2], and t[3] in top_trans
unique_nmos_nets = set(net for t in bot_trans for net in [t[1], t[2], t[3]])
unique_nmos_nets.add("dummy")
#print (unique_nmos_nets)
for c in range(num_cols):
    for net in unique_nmos_nets:
        nmos_net[(net, c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"nmos_net_{net}_c{c}")
    #nmos_net[("dummy",c)]  = model.addVar(vtype=gp.GRB.BINARY, name=f"nmos_dummy_{net}_c{c}")

# Constraint 1: one column and one orientation
# Transistor have to be placed in somewhere
for i,t in enumerate(top_trans):
    name,G,D,S,B,nfin = t
    if i == 0: # one trasistor placed in half space to remove flip case
        #model.addConstr(gp.quicksum(c_top[(i,c,o)] for c in half_gate_cols for o in [0,1]) == 1,name=f"top_assign_first_half_1_{t[0]}")
        #model.addConstr(gp.quicksum(c_top[(i,c,o)] for c in after_half_gate_cols for o in [0,1]) == 0,name=f"top_assign_second_half_0_{t[0]}")
        model.addConstr(gp.quicksum(c_top[(i,c,0)] for c in gate_cols) == 1,name=f"top_assign_orient_0_{t[0]}")
        model.addConstr(gp.quicksum(c_top[(i,c,1)] for c in gate_cols) == 0,name=f"top_assign_orient_1_{t[0]}")
    else:
        model.addConstr(gp.quicksum(c_top[(i,c,o)] for c in gate_cols for o in [0,1]) == 1,name=f"top_assign_{t[0]}")
    for c in gate_cols :
        model.addConstr(c_top[(i, c, 0)] + c_top[(i, c, 1)] <= pmos_net[(G, c)],name=f"pmos_net_G_{name}_col_{c}_o")
        for key in final_pmos_net_info[t]['source']:
            model.addConstr(c_top[(i, c, 0)] + final_pmos_net_info[t]['source'][key] - 1 <= pmos_net[(key, c - 1)],name=f"pmos_net_S_{name}_col_{c-1}_o0")
            model.addConstr(c_top[(i, c, 1)] + final_pmos_net_info[t]['source'][key] - 1 <= pmos_net[(key, c + 1)],name=f"pmos_net_S_{name}_col_{c+1}_o1")
        for key in final_pmos_net_info[t]['drain']:
            model.addConstr(c_top[(i, c, 0)] + final_pmos_net_info[t]['drain'][key] - 1 <= pmos_net[(key, c + 1)],name=f"pmos_net_D_{name}_col_{c+1}_o0")
            model.addConstr(c_top[(i, c, 1)] + final_pmos_net_info[t]['drain'][key] - 1 <= pmos_net[(key, c - 1)],name=f"pmos_net_D_{name}_col_{c-1}_o1")

        # model.addConstr(c_top[(i, c, 0)] <= pmos_net[(S, c - 1)],name=f"pmos_net_S_{name}_col_{c-1}_o0")
        # model.addConstr(c_top[(i, c, 0)] <= pmos_net[(D, c + 1)],name=f"pmos_net_D_{name}_col_{c+1}_o0")
        # model.addConstr(c_top[(i, c, 1)] <= pmos_net[(D, c - 1)],name=f"pmos_net_D_{name}_col_{c-1}_o1")
        # model.addConstr(c_top[(i, c, 1)] <= pmos_net[(S, c + 1)],name=f"pmos_net_S_{name}_col_{c+1}_o1")

for j,t in enumerate(bot_trans):
    name,G,D,S,B,nfin = t
    model.addConstr(gp.quicksum(c_bot[(j,c,o)] for c in gate_cols for o in [0,1]) == 1,name=f"bot_assign_{t[0]}")
    for c in gate_cols:
        model.addConstr(c_bot[(j, c, 0)] + c_bot[(j, c, 1)] <= nmos_net[(G, c)],name=f"nmos_net_G_{name}_col_{c}_o")
        for key in final_nmos_net_info[t]['source']:
            model.addConstr(c_bot[(j, c, 0)] + final_nmos_net_info[t]['source'][key] - 1 <= nmos_net[(key, c - 1)],name=f"nmos_net_S_{name}_col_{c-1}_o0")
            model.addConstr(c_bot[(j, c, 1)] + final_nmos_net_info[t]['source'][key] - 1 <= nmos_net[(key, c + 1)],name=f"nmos_net_S_{name}_col_{c+1}_o1")
        for key in final_nmos_net_info[t]['drain']:
            model.addConstr(c_bot[(j, c, 0)] + final_nmos_net_info[t]['drain'][key] - 1 <= nmos_net[(key, c + 1)],name=f"nmos_net_D_{name}_col_{c+1}_o0")
            model.addConstr(c_bot[(j, c, 1)] + final_nmos_net_info[t]['drain'][key] - 1 <= nmos_net[(key, c - 1)],name=f"nmos_net_D_{name}_col_{c-1}_o1")
        # model.addConstr(c_bot[(j, c, 0)] <= nmos_net[(S, c - 1)],name=f"nmos_net_S_{name}_col_{c-1}_o0")
        # model.addConstr(c_bot[(j, c, 0)] <= nmos_net[(D, c + 1)],name=f"nmos_net_D_{name}_col_{c+1}_o0")
        # model.addConstr(c_bot[(j, c, 1)] <= nmos_net[(D, c - 1)],name=f"nmos_net_D_{name}_col_{c-1}_o1")
        # model.addConstr(c_bot[(j, c, 1)] <= nmos_net[(S, c + 1)],name=f"nmos_net_S_{name}_col_{c+1}_o1")

# PMOS Row:
# at most one transistor can be placed in one column
for c in gate_cols:
    model.addConstr(gp.quicksum(c_top[(i,c,o)] for i in range(len(top_trans)) for o in [0,1]) <= 1,name=f"pmos_one_per_col_{c}")
    # Assign "dummy" net if no transistor is placed
    model.addConstr(gp.quicksum(c_top[(i, c, o)] for i in range(len(top_trans)) for o in [0,1]) + pmos_net[("dummy", c)] == 1,name=f"dummy_assign_pmos_col_{c}")
    for net1 in unique_pmos_nets:
        for net2 in unique_pmos_nets:
            if net1 != "dummy" and net2 != "dummy" and net1 != net2:
                model.addConstr(pmos_net[("dummy", c)] + pmos_net[(net1, c-1)] + pmos_net[(net2, c+1)] <= 2 + nmos_net[("dummy", c)], 
                                name=f"avoid_different_nets_{net1}_{net2}_col_{c}")
    model.addConstr(pmos_net[("dummy", c)] + pmos_net[("dummy", c-1)] <= 1)
    model.addConstr(pmos_net[("dummy", c)] + pmos_net[("dummy", c+1)] <= 1)

# NMOS Row:
    model.addConstr(gp.quicksum(c_bot[(j,c,o)] for j in range(len(bot_trans)) for o in [0,1]) <= 1,name=f"nmos_one_per_col_{c}")
    model.addConstr(gp.quicksum(c_bot[(j,c,o)] for j in range(len(bot_trans)) for o in [0,1]) + nmos_net[("dummy", c)] == 1,name=f"dummy_assign_nmos_col_{c}")
    for net1 in unique_nmos_nets:
        for net2 in unique_nmos_nets:
            if net1 != "dummy" and net2 != "dummy" and net1 != net2:
                model.addConstr(nmos_net[("dummy", c)] + nmos_net[(net1, c-1)] + nmos_net[(net2, c+1)] <= 2 + pmos_net[("dummy", c)], 
                                name=f"avoid_different_nets_{net1}_{net2}_col_{c}")
    model.addConstr(nmos_net[("dummy", c)] + nmos_net[("dummy", c-1)] <= 1)
    model.addConstr(nmos_net[("dummy", c)] + nmos_net[("dummy", c+1)] <= 1)

for c in range(num_cols):
    model.addConstr(gp.quicksum(pmos_net[(net, c)] for net in unique_pmos_nets) == 1,name=f"pmos_one_net_per_col_{c}")
    model.addConstr(gp.quicksum(nmos_net[(net, c)] for net in unique_nmos_nets) == 1,name=f"pmos_one_net_per_col_{c}")

# misalign temporarily
misalign_c = {}
temp_misalign_c={} #
misalign_net_c = {}
temp_misalign_net_c = {}
dummyalign_c = {}
dummyalign_or_misalign_c = {}
clock_net=['cki','ncki']
for c in gate_cols:
    misalign_c[c] = model.addVar(vtype=gp.GRB.BINARY, name=f"misalign_c{c}")
    temp_misalign_c[c] = model.addVar(vtype=gp.GRB.BINARY, name=f"temp_misalign_c{c}")
    dummyalign_c[c] = model.addVar(vtype=gp.GRB.BINARY, name=f"dummayallign_c{c}")
    dummyalign_or_misalign_c[c] = model.addVar(vtype=gp.GRB.BINARY, name=f"dummy_or_misalign_c{c}")
    model.addConstr(dummyalign_or_misalign_c[c] >= dummyalign_c[c],name=f"dummy_or_misalign_ge_dummy_{c}")
    model.addConstr(dummyalign_or_misalign_c[c] >= misalign_c[c],name=f"dummy_or_misalign_ge_mis_{c}")
    model.addConstr(dummyalign_or_misalign_c[c] <= dummyalign_c[c] + misalign_c[c],name=f"dummy_or_misalign_le_sum_{c}")
    for net in shared_net:
        if net in clock_net: #
            misalign_net_c[(net,c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"misalign_net_c{c}")
            model.addConstr(misalign_net_c[(net, c)] >= pmos_net[(net, c)] - nmos_net[(net, c)], name=f"misalign_c_rule1_{net}_c{c}")
            model.addConstr(misalign_net_c[(net, c)] >= nmos_net[(net, c)] - pmos_net[(net, c)], name=f"misalign_c_rule2_{net}_c{c}")
            model.addConstr(misalign_net_c[(net, c)] <= nmos_net[(net, c)] + pmos_net[(net, c)], name=f"misalign_c_rule3_{net}_c{c}")
            model.addConstr(misalign_net_c[(net, c)] <= 2 - (nmos_net[(net, c)] + pmos_net[(net, c)]), name=f"misalign_c_rule4_{net}_c{c}")
            model.addConstr(misalign_c[c] >= misalign_net_c[(net,c)],name=f"misalign_c_ge_misalign_net_{net}_c{c}")
        else: #
            temp_misalign_net_c[(net,c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"temp_misalign_net_c{c}") #
            model.addConstr(temp_misalign_net_c[(net, c)] >= pmos_net[(net, c)] - nmos_net[(net, c)], name=f"temp_misalign_c_rule1_{net}_c{c}") #
            model.addConstr(temp_misalign_net_c[(net, c)] >= nmos_net[(net, c)] - pmos_net[(net, c)], name=f"temp_misalign_c_rule2_{net}_c{c}") #
            model.addConstr(temp_misalign_net_c[(net, c)] <= nmos_net[(net, c)] + pmos_net[(net, c)], name=f"temp_misalign_c_rule3_{net}_c{c}") #
            model.addConstr(temp_misalign_net_c[(net, c)] <= 2 - (nmos_net[(net, c)] + pmos_net[(net, c)]), name=f"temp_misalign_c_rule4_{net}_c{c}") #
            model.addConstr(temp_misalign_c[c] >= temp_misalign_net_c[(net,c)],name=f"temp_misalign_c_ge_temp_misalign_net_{net}_c{c}") #
    model.addConstr(
        misalign_c[c] <= gp.quicksum(misalign_net_c[(net, c)] for net in shared_net if net in clock_net), #
        #misalign_c[c] <= gp.quicksum(misalign_net_c[(net, c)] for net in shared_net),
        name=f"misalign_c_le_sum_mis_net_c{c}"
    )
    model.addConstr( #
        temp_misalign_c[c] <= gp.quicksum(temp_misalign_net_c[(net, c)] for net in shared_net if net not in clock_net), #
        name=f"temp_misalign_c_le_sum_mis_net_c{c}" #
    ) #
    model.addConstr(dummyalign_c[c] <= pmos_net[("dummy", c)], name=f"dummyalign_c_rule1_c{c}")
    model.addConstr(dummyalign_c[c] <= nmos_net[("dummy", c)], name=f"dummyalign_c_rule2_c{c}")
    model.addConstr(dummyalign_c[c] >= pmos_net[("dummy", c)] + nmos_net[("dummy", c)] - 1, name=f"dummyalign_c_rule3_c{c}")
model.addConstr(gp.quicksum(misalign_c[c] for c in gate_cols) == misalign_col, name=f"misalign_col_maximum")
model.addConstr(gp.quicksum(temp_misalign_c[c] for c in gate_cols) == 0, name=f"temp_misalign_col_maximum") #

# gate cut constraint
consecutive = 2 #temp
for i in range(len(gate_cols) - consecutive + 1):
    if i == 0:
        prev_x = 0
    else:
        prev_x = dummyalign_or_misalign_c[ gate_cols[i - 1] ]
    block_cols = gate_cols[i : i + consecutive]
    model.addConstr(gp.quicksum(dummyalign_or_misalign_c[c] for c in block_cols) >= consecutive * (misalign_c[gate_cols[i]] - prev_x), name=f"consecutive_gate_cut_c{gate_cols[i]}")
    #for d in range(1, consecutive):
        #pass
        #print (i,d,gate_cols[i],gate_cols[i+d])
        #model.addConstr(misalign_c[gate_cols[i]] <= misalign_c[gate_cols[i + d]], name=f"consecutive_gate_cut_c{c}_{d}")

# flow left and right
flow_limit = MAX_TRACK + len(upper_rows)
a_l_c = {}
b_l_c = {}
for c in gate_cols:
    #print (c,columns,column_positions)
    for net in unique_pmos_nets:
        if net != "dummy" and net not in power_net:
            a_l_c[(net,c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"a_net_{net}_col{c}_left")
            model.addConstr(a_l_c[(net,c)] <= pmos_net[(net, c-1)],name=f"a_net_le_pmos_{net}_col{c}_left")
            if net in shared_sd:
                sum_other = gp.quicksum(pmos_net[(net, x)]+nmos_net[(net, x)] for x in columns if x != c and x != (c-1))
            else:
                sum_other = gp.quicksum(pmos_net[(net, x)] for x in columns if x != c and x != (c-1))
            model.addConstr(a_l_c[(net,c)] <= sum_other,name=f"a_net_le_sumother_{net}_col{c}_left")
            model.addConstr(len(columns)*(a_l_c[(net,c)]+1-pmos_net[(net,c-1)]) >= sum_other,name=f"a_net_ge_sumother_{net}_col{c}_left")
    for net in unique_nmos_nets:
        if net != "dummy" and net not in power_net:
            b_l_c[(net,c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"b_net_{net}_col{c}_left")
            model.addConstr(b_l_c[(net,c)] <= nmos_net[(net, c-1)],name=f"b_net_le_nmos_{net}_col{c}_left")
            if net in shared_sd:
                model.addConstr(b_l_c[(net,c)] <= 1-a_l_c[(net,c)],name=f"b_net_already_{net}_col{c}_left")
                sum_other = gp.quicksum(nmos_net[(net, x)]+pmos_net[(net,x)] for x in columns if x != c and x != (c-1))
                model.addConstr(len(columns)*(b_l_c[(net,c)]+1-(nmos_net[(net, c-1)]-pmos_net[(net, c-1)])) >= sum_other,name=f"b_net_ge_sumother_{net}_col{c}_left")
            else:
                sum_other = gp.quicksum(nmos_net[(net, x)] for x in columns if x != c and x != (c-1))
                model.addConstr(len(columns)*(b_l_c[(net,c)]+1-nmos_net[(net, c-1)]) >= sum_other,name=f"b_net_ge_sumother_{net}_col{c}_left")
            model.addConstr(b_l_c[(net,c)] <= sum_other,name=f"b_net_le_sumother_{net}_col{c}_left")
            
a_left_c = {}
b_left_c = {}
for c in gate_cols:
    a_left_c[c] = gp.quicksum(a_l_c.get((net,c), 0) for net in unique_pmos_nets if net != "dummy")
    b_left_c[c] = gp.quicksum(b_l_c.get((net,c), 0) for net in unique_nmos_nets if net != "dummy")

a_r_c = {}
b_r_c = {}
for c in gate_cols:
    #print (c,columns,column_positions)
    for net in unique_pmos_nets:
        if net != "dummy" and net not in power_net:
            a_r_c[(net,c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"a_net_{net}_col{c}_right")
            model.addConstr(a_r_c[(net,c)] <= pmos_net[(net, c+1)],name=f"a_net_le_pmos_{net}_col{c}_right")
            if net in shared_sd:
                sum_other = gp.quicksum(pmos_net[(net, x)]+nmos_net[(net, x)] for x in columns if x != c and x != (c+1))
            else:
                sum_other = gp.quicksum(pmos_net[(net, x)] for x in columns if x != c and x != (c+1))
            model.addConstr(a_r_c[(net,c)] <= sum_other,name=f"a_net_le_sumother_{net}_col{c}_right")
            model.addConstr(len(columns)*(a_r_c[(net,c)]+1-pmos_net[(net,c+1)]) >= sum_other,name=f"a_net_ge_sumother_{net}_col{c}_right")
    for net in unique_nmos_nets:
        if net != "dummy" and net not in power_net:
            b_r_c[(net,c)] = model.addVar(vtype=gp.GRB.BINARY, name=f"b_net_{net}_col{c}_right")
            model.addConstr(b_r_c[(net,c)] <= nmos_net[(net, c+1)],name=f"b_net_le_nmos_{net}_col{c}_right")
            if net in shared_sd:
                model.addConstr(b_r_c[(net,c)] <= 1-a_r_c[(net,c)],name=f"b_net_already_{net}_col{c}_right")
                sum_other = gp.quicksum(nmos_net[(net, x)]+pmos_net[(net,x)] for x in columns if x != c and x != (c+1))
                model.addConstr(len(columns)*(b_r_c[(net,c)]+1-(nmos_net[(net, c+1)]-pmos_net[(net, c+1)])) >= sum_other,name=f"b_net_ge_sumother_{net}_col{c}_right")
            else:  
                sum_other = gp.quicksum(nmos_net[(net, x)] for x in columns if x != c and x != (c+1))
                model.addConstr(len(columns)*(b_r_c[(net,c)]+1-nmos_net[(net, c+1)]) >= sum_other,name=f"b_net_ge_sumother_{net}_col{c}_right")
            model.addConstr(b_r_c[(net,c)] <= sum_other,name=f"b_net_le_sumother_{net}_col{c}_right")

a_right_c = {}
b_right_c = {}
for c in gate_cols:
    a_right_c[c] = gp.quicksum(a_r_c.get((net,c), 0) for net in unique_pmos_nets if net != "dummy")
    b_right_c[c] = gp.quicksum(b_r_c.get((net,c), 0) for net in unique_nmos_nets if net != "dummy")

a_c = {}
b_c = {}
for c in gate_cols:
    a_c[c] = model.addVar(vtype=gp.GRB.BINARY, name=f"a_{net}_col{c}_final")
    b_c[c] = model.addVar(vtype=gp.GRB.BINARY, name=f"b_{net}_col{c}_final")
    model.addConstr(a_c[c]>=a_left_c[c],name=f"a_{net}_col{c}_rule1")
    model.addConstr(a_c[c]>=a_right_c[c],name=f"a_{net}_col{c}_rule2")
    model.addConstr(a_c[c]<=a_left_c[c]+a_right_c[c],name=f"a_{net}_col{c}_rule3")
    model.addConstr(b_c[c]>=b_left_c[c],name=f"b_{net}_col{c}_rule1")
    model.addConstr(b_c[c]>=b_right_c[c],name=f"b_{net}_col{c}_rule2")
    model.addConstr(b_c[c]<=b_left_c[c]+b_right_c[c],name=f"b_{net}_col{c}_rule3")

e_net_c = {}
e_c = {}
for cidx, c in enumerate(gate_cols):
    tmp_list = []
    left_cols  = [x for x in columns if x <= c-2]
    right_cols = [x for x in columns if x >= c+2]
    for net in total_nets:
        if net not in power_net:
            ename = f"e_net_{net}_col{c}"
            ev = model.addVar(vtype=gp.GRB.BINARY, name=ename)
            left_exist = model.addVar(vtype=gp.GRB.BINARY, name=f"left_{net}_exist_{c}")
            right_exist = model.addVar(vtype=gp.GRB.BINARY, name=f"right_{net}_exist_{c}")
            if net in shared_net:
                left_sum = gp.quicksum(pmos_net[(net, x)] + nmos_net[(net, x)] for x in left_cols)
                right_sum = gp.quicksum(pmos_net[(net, x)] + nmos_net[(net, x)] for x in right_cols)
            elif net in unique_pmos_nets:
                left_sum = gp.quicksum(pmos_net[(net, x)] for x in left_cols)
                right_sum = gp.quicksum(pmos_net[(net, x)] for x in right_cols)
            elif net in unique_nmos_nets:
                left_sum = gp.quicksum(nmos_net[(net, x)] for x in left_cols)
                right_sum = gp.quicksum(nmos_net[(net, x)] for x in right_cols)
            model.addConstr(left_exist <= left_sum,f"left_exist_rule1_{c}_{net}")
            model.addConstr(len(columns)*left_exist >= left_sum,f"left_exist_rule2_{c}_{net}")                
            model.addConstr(right_exist <= right_sum,f"right_exist_rule1_{c}_{net}")
            model.addConstr(len(columns)*right_exist >= right_sum,f"right_exist_rule2_{c}_{net}")
            model.addConstr(ev <= left_exist,f"min_cut_rule1_{c}_{net}")
            model.addConstr(ev <= right_exist,f"min_cut_rule2_{c}_{net}")
            model.addConstr(len(columns)*ev >= left_exist+right_exist-1,f"min_cut_rule3_{c}_{net}")
            e_net_c[(net,c)] = ev
            tmp_list.append(ev)
        e_c[c] = gp.quicksum(tmp_list)

flow_estimator={}
for c in gate_cols:
    track_expr       = a_c[c] + b_c[c] + (1 + misalign_c[c])
    track_ext_expr   = track_expr + e_c[c]
    flow_estimator[c] = track_ext_expr
    model.addConstr(track_expr <= MAX_TRACK,name=f"track_limit_col{c}")
    model.addConstr(track_ext_expr <= flow_limit,name=f"track_plus_e_limit_col{c}")

### Routing Start
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
t_c = {}         # Integer variables: total track cost at column c
t_c_r = {}       # Integer variables: total track cost at column c, row r
t_n_c_r = {}     # Binary variables: net n uses track at column c, row r
ut_c = {}        # Binary variables: upper track cost at column c
ut_c_r = {}      # Binary variables: upper track cost at column c, row r
ut_n_c_r = {}    # Binary variables: net n uses upper track cost at column c, row r

# for flow
sum_actives_vars={}   # To store sum_active_vars variables
is_root_node = {}     # Define is_root_node variables
min_c={}              # bounding box min
max_c={}              # bounding box max
indicator_i_vars = {} # Define indicator_i_vars
net_flow={}           # Flow conservation constraints
f_n_c_r = {}     # Integer variables: net n flow variable for edge at column c and row r
f_n_c_ur = {}    # Integer variables: net n flow variable for edge at column c and upper row ur
y_n_c_r = {}     # Binary variables: net n flow variable row selection at column c
flow_cap={}
flow_cap2={}
cap_i={}
#s_i={}
z_f={} #Auxiliary Variable for net flow
# for MAR
# edge_left={}
# edge_right={}
# edge_metal={}
# edge_eol_l={}
# edge_eol_r={}
io_marker={}
c_left={}
c_right={}
c_metal={}
c_eol_l={}
c_eol_r={}
c_mar_row={}
case={}
isOutLeft={}
isLeft={}
isBetween={}
isRight={}
isOutRight={}
min_indicator={} #bbox, root node
max_indicator={} #bbox
max_bbox={} #bbox

for c in columns:
    t_c[c] = model.addVar(vtype=gp.GRB.INTEGER, name=f"t_c_{c}")
    ut_c[c] = model.addVar(vtype=gp.GRB.INTEGER, name=f"ut_c_{c}")
    for r in rows:
        t_c_r[c, r] = model.addVar(vtype=gp.GRB.INTEGER, name=f"t_c_{c}_{r}")
    for r in upper_rows:
        ut_c_r[c,r] = model.addVar(vtype=gp.GRB.INTEGER, name=f"ut_c_{c}_{r}")

# eol
new_net_name = 'eol'
t_n_c_r[new_net_name] = model.addVars(columns, rows, vtype=gp.GRB.BINARY, name=f"t_{new_net_name}_c_r")
ut_n_c_r[new_net_name] = model.addVars(columns, upper_rows, vtype=gp.GRB.BINARY, name=f"ut_{new_net_name}_c_r")

### Routing constraint

# placed net -> indicator pp nn ac
for net in total_nets:
    if net not in power_net:
        if net in io_pins:
            io_marker[net]=1
        else :
            io_marker[net]=0
        t_n_c_r[net] = model.addVars(columns, rows, vtype=gp.GRB.BINARY, name=f"t_{net}_c_r")
        v_n_v[net] = model.addVars(via_indices, vtype=gp.GRB.BINARY, name=f"v_{net}_v")
        ut_n_c_r[net] = model.addVars(columns, upper_rows, vtype=gp.GRB.BINARY, name=f"ut_{net}_c_r")
        cap = g_net_count[net] + math.ceil(sd_net_count[net]/2) + dummy_padding
        min_indicator[net] = model.addVar(vtype=gp.GRB.INTEGER, lb=0, ub=num_cols - 1, name=f"min_indicator_{net}")
        max_bbox[net] = model.addVar(vtype=gp.GRB.INTEGER, lb=0, ub=num_cols - 1, name=f"max_bbox_{net}")

        #min_c[net] = model.addVar(vtype=gp.GRB.INTEGER, name=f"min_c_{net}")
        #max_c[net] = model.addVar(vtype=gp.GRB.INTEGER, name=f"max_c_{net}")
        for c in range(num_cols) :
            pos_p = f"pp_{3 + 3 * c}"
            pos_n = f"nn_{3 + 3 * c}"
            pos_a = f"ac_{3 + 3 * c}"
            indicator_i_vars[net,pos_p] = model.addVar(vtype=gp.GRB.BINARY, name=f"indicator_{net}_{pos_p}")
            indicator_i_vars[net,pos_n] = model.addVar(vtype=gp.GRB.BINARY, name=f"indicator_{net}_{pos_n}")
            indicator_i_vars[net,pos_a] = model.addVar(vtype=gp.GRB.BINARY, name=f"indicator_{net}_{pos_a}")
            is_root_node[net, pos_p] = model.addVar(vtype=gp.GRB.BINARY, name=f"root_node_{net}_{pos_p}")
            is_root_node[net, pos_n] = model.addVar(vtype=gp.GRB.BINARY, name=f"root_node_{net}_{pos_n}")
            is_root_node[net, pos_a] = model.addVar(vtype=gp.GRB.BINARY, name=f"root_node_{net}_{pos_a}")
            max_indicator[net, pos_p] = model.addVar(vtype=gp.GRB.BINARY, name=f"max_indicator_{net}_{pos_p}")
            max_indicator[net, pos_n] = model.addVar(vtype=gp.GRB.BINARY, name=f"max_indicator_{net}_{pos_n}")
            max_indicator[net, pos_a] = model.addVar(vtype=gp.GRB.BINARY, name=f"max_indicator_{net}_{pos_a}")
            model.addConstr(indicator_i_vars[net, pos_p] >= is_root_node[net, pos_p], name=f"root_find_{net}_{pos_p}")
            model.addConstr(indicator_i_vars[net, pos_n] >= is_root_node[net, pos_n], name=f"root_find_{net}_{pos_n}")
            model.addConstr(indicator_i_vars[net, pos_a] >= is_root_node[net, pos_a], name=f"root_find_{net}_{pos_a}")
            model.addConstr(indicator_i_vars[net, pos_p] >= max_indicator[net, pos_p], name=f"max_indicator_find_{net}_{pos_p}")
            model.addConstr(indicator_i_vars[net, pos_n] >= max_indicator[net, pos_n], name=f"max_indicator_find_{net}_{pos_n}")
            model.addConstr(indicator_i_vars[net, pos_a] >= max_indicator[net, pos_a], name=f"max_indicator_find_{net}_{pos_a}")            
            if net in unique_pmos_nets and net in unique_nmos_nets:
                model.addConstr(indicator_i_vars[net, pos_a] >= pmos_net[(net, c)] + nmos_net[(net, c)] - 1, name=f"lower_bound_{net}_{pos_a}")
                model.addConstr(indicator_i_vars[net, pos_a] <= pmos_net[(net, c)], name=f"upper_bound_v1_{net}_{pos_a}")
                model.addConstr(indicator_i_vars[net, pos_a] <= nmos_net[(net, c)], name=f"upper_bound_v2_{net}_{pos_a}")
                model.addConstr(indicator_i_vars[net, pos_p] == pmos_net[(net, c)] - indicator_i_vars[net, pos_a], name=f"combined_net_{net}_{pos_p}")
                model.addConstr(indicator_i_vars[net, pos_n] == nmos_net[(net, c)] - indicator_i_vars[net, pos_a], name=f"combined_net_{net}_{pos_n}")
            else:
                if net in unique_pmos_nets:
                    model.addConstr(indicator_i_vars[net,pos_p] == pmos_net[(net,c)], name=f"link_pmos_net_and_indicator_{net}_{pos_p}")
                    model.addConstr(indicator_i_vars[net,pos_n] == 0, name=f"pmos_only_net_indicator_zero_{net}_{pos_n}")
                    model.addConstr(indicator_i_vars[net,pos_a] == 0, name=f"pmos_only_net_indicator_zero_{net}_{pos_a}")
                if net in unique_nmos_nets:
                    model.addConstr(indicator_i_vars[net,pos_n] == nmos_net[(net,c)], name=f"link_nmos_net_and_indicator_{net}_{pos_n}")
                    model.addConstr(indicator_i_vars[net,pos_p] == 0, name=f"nmos_only_net_indicator_zero_{net}_{pos_p}")
                    model.addConstr(indicator_i_vars[net,pos_a] == 0, name=f"nmos_only_net_indicator_zero_{net}_{pos_a}")

            # root node minimun
            model.addConstr(min_indicator[net] <= c + (1 - indicator_i_vars[net, pos_p]) * num_cols,name=f"min_indicator_constr_p_{net}_{c}")
            model.addConstr(min_indicator[net] <= c + (1 - indicator_i_vars[net, pos_n]) * num_cols,name=f"min_indicator_constr_n_{net}_{c}")
            model.addConstr(min_indicator[net] <= c + (1 - indicator_i_vars[net, pos_a]) * num_cols,name=f"min_indicator_constr_a_{net}_{c}")
            model.addConstr(is_root_node[net, pos_p]*c <= min_indicator[net], name=f"root_node_match_p_{net}_{c}")
            model.addConstr(is_root_node[net, pos_n]*c <= min_indicator[net], name=f"root_node_match_n_{net}_{c}")
            model.addConstr(is_root_node[net, pos_a]*c <= min_indicator[net], name=f"root_node_match_a_{net}_{c}")
            # maximun bbox
            model.addConstr(max_bbox[net] >= c - (1 - indicator_i_vars[net, pos_p]) * num_cols,name=f"max_bbox_constr_p_{net}_{c}")
            model.addConstr(max_bbox[net] >= c - (1 - indicator_i_vars[net, pos_n]) * num_cols,name=f"max_bbox_constr_n_{net}_{c}")
            model.addConstr(max_bbox[net] >= c - (1 - indicator_i_vars[net, pos_a]) * num_cols,name=f"max_bbox_constr_a_{net}_{c}")
            model.addConstr((num_cols-1)*(1-max_indicator[net, pos_p])+max_indicator[net, pos_p]*c >= max_bbox[net], name=f"max_indicator_match_p_{net}_{c}")
            model.addConstr((num_cols-1)*(1-max_indicator[net, pos_n])+max_indicator[net, pos_n]*c >= max_bbox[net], name=f"max_indicator_match_n_{net}_{c}")
            model.addConstr((num_cols-1)*(1-max_indicator[net, pos_a])+max_indicator[net, pos_a]*c >= max_bbox[net], name=f"max_indicator_match_a_{net}_{c}")
        
        sum_actives = gp.quicksum(indicator_i_vars[net,f"pp_{3 + 3 * c}"]+indicator_i_vars[net,f"nn_{3 + 3 * c}"]+indicator_i_vars[net,f"ac_{3 + 3 * c}"] for c in range(num_cols))
        sum_actives_vars[(net)] = sum_actives
        model.addConstr(gp.quicksum(is_root_node[net,f"pp_{3 + 3 * c}"]+is_root_node[net,f"nn_{3 + 3 * c}"]+is_root_node[net,f"ac_{3 + 3 * c}"] for c in range(num_cols)) == 1, name=f"one_root_node_enable_{net}")
        model.addConstr(gp.quicksum(max_indicator[net,f"pp_{3 + 3 * c}"]+max_indicator[net,f"nn_{3 + 3 * c}"]+max_indicator[net,f"ac_{3 + 3 * c}"] for c in range(num_cols)) == 1, name=f"one_max_indicator_enable_{net}")

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
                var_name = f"y_{net}_edge_connector_{i}_{j}_co"
                flow_var_name = f"f_{net}_edge_connector_{i}_{j}_co"
                y_n_c_r[net][i, j, 'co'] = model.addVar(vtype=gp.GRB.BINARY, name=var_name)
                model.addConstr(y_n_c_r[net][i, j, 'co'] <= indicator_i_vars[net,j], f"on_off_constraint_by_indicator_{net}_{i}_{j}_co")
                model.addConstr(y_n_c_r[net][i, j, 'co'] <= io_detector, f"on_off_constraint_by_sum_actives_{net}_{i}_{j}_co")
                model.addConstr(y_n_c_r[net][i, j, 'co'] >= indicator_i_vars[net,j]+io_detector-1, f"on_off_constraint_by_mixing_{net}_{i}_{j}_co")
                f_n_c_r[net][i, j, 'co'] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.INTEGER, name=flow_var_name)
                #f_n_c_r[net][i, j, 'co'] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.CONTINUOUS, name=flow_var_name)
                model.addConstr(f_n_c_r[net][i, j, 'co'] <= cap * y_n_c_r[net][i, j, 'co'], name=f'edge_flow_ub_{net}_{i}_{j}_ve')
                model.addConstr(f_n_c_r[net][i, j, 'co'] >= -cap * y_n_c_r[net][i, j, 'co'],name=f'edge_flow_lb_{net}_{i}_{j}_ve')
            
            # MAR !!!
            #if io_marker[net] == 1:
            for c in range(num_cols) :
                pos_p = f"pp_{3 + 3 * c}"
                pos_n = f"nn_{3 + 3 * c}"
                pos_a = f"ac_{3 + 3 * c}"
                target_list = get_list_set(c,M_MAR,num_cols) # 2 to 3 gear ratio -> divided 3
                for j in [pos_p, pos_n, pos_a]:
                    j_prefix = j.split('_')[0]
                    #print (c, j, j_prefix, target_list, len(target_list))
                    if j_prefix == 'ac':
                        target_rows = rows
                    elif j_prefix == 'pp':
                        target_rows = pmos_rows
                    elif j_prefix == 'nn':
                        target_rows = nmos_rows
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
                            #print (net,j,r,n,l,l_l,MAR+2)
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
                j_prefix, j_num = j.split('_')[0], int(j.split('_')[1])
                cal_c = (j_num - 1) // 3 # divisor = 3
                #print (i,j,cal_c)
                if j_prefix == 'middle':
                    target_rows = [middle_row]
                elif j_prefix == 'pv':
                    target_rows = pmos_rows
                elif j_prefix == 'nv':
                    target_rows = nmos_rows
                for row in target_rows:
                    var_name = f"y_{net}_edge_{i}_{j}_{row}"
                    flow_var_name = f"f_{net}_edge_{i}_{j}_{row}"
                    y_n_c_r[net][i,j,row] = model.addVar(vtype=gp.GRB.BINARY, name=var_name)
                    f_n_c_r[net][i,j,row] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.INTEGER, name=flow_var_name)
                    #f_n_c_r[net][i,j,row] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.CONTINUOUS, name=flow_var_name)
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
                j_prefix, j_num = j.split('_')[0], int(j.split('_')[1])
                cal_c = (j_num - 1) // 3 # divisor = 3
                if j.startswith('pv_') or j.startswith('nv_') or j.startswith('middle_'):
                    var_name = f"y_{net}_edge_via_enable_{i}_{j}"
                    flow_var_name = f"f_{net}_edge_via_enable_{i}_{j}"
                    y_n_c_r[net][i, j, 've'] = model.addVar(vtype=gp.GRB.BINARY, name=var_name)
                    model.addConstr(y_n_c_r[net][i, j, 've'] <= sum_actives-1,f"global_zero_constraint_{net}_{i}_{j}_ve")
                    model.addConstr((min_indicator[net]-bbox)-cal_c <= num_cols*(1 - y_n_c_r[net][i, j, 've']), name=f"active_c_ge_min_indicator_min_one_{net}_{i}_{j}_ve")
                    model.addConstr(cal_c-(max_bbox[net]+bbox) <= num_cols*(1 - y_n_c_r[net][i, j, 've']), name=f"active_c_ge_max_bbox_min_bbox_{net}_{i}_{j}_ve")
                    f_n_c_ur[net][i, j, 've'] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.INTEGER, name=flow_var_name)
                    #f_n_c_ur[net][i, j, 've'] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.CONTINUOUS, name=flow_var_name)
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
                    for row in upper_rows:
                        var_name = f"y_{net}_edge_{i}_{j}_r_{row}"
                        flow_var_name = f"f_{net}_edge_{i}_{j}_r_{row}"
                        y_n_c_r[net][i,j,row] = model.addVar(vtype=gp.GRB.BINARY, name=var_name)
                        model.addConstr(y_n_c_r[net][i, j, row] <= sum_actives-1,f"global_zero_constraint_{net}_{i}_{j}_{row}")
                        model.addConstr((min_indicator[net]-bbox)-cal_c <= num_cols*(1 - y_n_c_r[net][i, j, row]), name=f"active_c_ge_min_indicator_min_one_{net}_{i}_{j}_{row}")
                        model.addConstr(cal_c-(max_bbox[net]+bbox) <= num_cols*(1 - y_n_c_r[net][i, j, row]), name=f"active_c_ge_max_bbox_min_bbox_{net}_{i}_{j}_{row}")
                        f_n_c_ur[net][i,j,row] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.INTEGER, name=flow_var_name)
                        #f_n_c_ur[net][i,j,row] = model.addVar(lb=-cap, ub=cap, vtype=gp.GRB.CONTINUOUS, name=flow_var_name)
                        model.addConstr(f_n_c_ur[net][i, j, row] <= cap * y_n_c_r[net][i, j, row],name=f'edge_flow_ub_{net}_{i}_{j}_{row}')
                        model.addConstr(f_n_c_ur[net][i, j, row] >= -cap * y_n_c_r[net][i, j, row],name=f'edge_flow_lb_{net}_{i}_{j}_{row}')
                        # flow_cap2[net][i, j, row] = model.addVar(vtype=gp.GRB.INTEGER, name=f"flow_cap_{net}_edge")
                        # model.addConstr(flow_cap2[net][i, j, row] <= cap * y_n_c_r[net][i, j, row], "flow_cap_lim1")
                        # model.addConstr(flow_cap2[net][i, j, row] <= sum_actives-1, "flow_cap_lim2")
                        # model.addConstr(flow_cap2[net][i, j, row] >= sum_actives-1 - cap * (1 - y_n_c_r[net][i, j, row]), "flow_cap_lim3")
                        # model.addConstr(flow_cap2[net][i, j, row] >= 0, "flow_cap_lim4")
                        # model.addConstr(f_n_c_ur[net][i, j, row] >= -flow_cap2[net][i, j, row], "flow_lb")
                        # model.addConstr(f_n_c_ur[net][i, j, row] <=  flow_cap2[net][i, j, row], "flow_ub")

            #print("Big : ",big)
            for m1 in m1_columns:
                #print (pos_i)
                v_i = int(m1.split('_')[1])
                v_index = via_positions.index(v_i)
                model.addConstr(y_n_c_r[net][m1, f"pv_{v_i}", f"ve"] <= v_n_v[net][v_index], name=f"via_enable_{net}_{pos_i}_pv_{v_i}")
                model.addConstr(y_n_c_r[net][m1, f"nv_{v_i}", f"ve"] <= v_n_v[net][v_index], name=f"via_enable_{net}_{pos_i}_nv_{v_i}")
                if MAX_TRACK % 2 == 1:
                    model.addConstr(y_n_c_r[net][m1, f"middle_{v_i}", f"ve"] <= v_n_v[net][v_index], name=f"via_enable_{net}_{pos_i}_middle_{v_i}")

            # edge -> track cost
            for i, j in Edges:
                i_prefix, i_num = i.split('_')[0], int(i.split('_')[1])
                j_prefix, j_num = j.split('_')[0], int(j.split('_')[1])
                if j_prefix != 'ac' and j_prefix != 'pp' and j_prefix != 'nn':
                    # flow -> row selection -> track cost
                    if i_num > j_num:
                        i_num, j_num = j_num, i_num
                        i_prefix, j_prefix = j_prefix, i_prefix
                    i_index = i_num // 3 - 1
                    if i_num not in column_positions:  # only for 2 to 3
                        i_diff_1 = 3*(i_index + 2)-i_num
                        i_diff_2 = i_num-3*(i_index+1)
                        if i_diff_1 <= i_diff_2 and i_diff_1 <= V_OVL:
                            i_index = i_num // 3
                            #print (i,i_num,i_index,iasdsa_index)
                    if j_num in column_positions:
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
                        if j_prefix == 'middle':
                            target_rows = [middle_row]
                        elif j_prefix == 'pv':
                            target_rows = pmos_rows
                        elif j_prefix == 'nv':
                            target_rows = nmos_rows
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
                            for r in upper_rows:
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
                i_prefix, i_num = pos_i.split('_')[0], int(pos_i.split('_')[1])
                
                if i_prefix == 'middle':
                    target_rows = [middle_row]
                elif i_prefix == 'pv':
                    target_rows = pmos_rows
                elif i_prefix == 'nv':
                    target_rows = nmos_rows

                if i_prefix == 'm1':
                    inflow = gp.quicksum(f_n_c_ur[net][j, k, r] for j, k in Edges_m1 if k == pos_i and j.startswith('m1') for r in upper_rows)
                    outflow = gp.quicksum(f_n_c_ur[net][j, k, r] for j, k in Edges_m1 if j == pos_i and k.startswith('m1') for r in upper_rows) + gp.quicksum(f_n_c_ur[net][j, k, 've'] for j, k in Edges_m1 if j == pos_i and not k.startswith('m1'))
                elif i_prefix == 'pv' or i_prefix == 'nv' or i_prefix == 'middle':
                    if i_num in column_positions:
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
                cap_i[net, pos_i] = model.addVar(vtype=gp.GRB.INTEGER, lb=-cap, ub=1, name=f"cap_{net}_{pos_i}")
                #cap_i[net, pos_i] = model.addVar(vtype=gp.GRB.CONTINUOUS, lb=-cap, ub=1, name=f"cap_{net}_{pos_i}")
                # Combine root node and non-root constraints
                # If is_root_node[net, pos_i] is True -> cap_i = 1 - sum_actives
                # If is_root_node[net, pos_i] is False -> cap_i = 1 or -1
                if pos_i in wo_via_points:
                    #s_i[net, pos_i] = model.addVar(vtype=gp.GRB.BINARY, name=f"s_{net}_{pos_i}")
                    #model.addConstr(s_i[net, pos_i]<=indicator_i_vars[net, pos_i],name=f"binary_on_off_{net}_{pos_i}")
                    model.addGenConstrIndicator(
                        is_root_node[net, pos_i], True,
                        #cap_i[net, pos_i] == gp.LinExpr(1.0) - sum_actives,
                        cap_i[net, pos_i] == 1 - sum_actives,
                        #cap_i[net, pos_i] == -1,
                        name=f"t_definition_root_{net}_{pos_i}"
                    )
                    model.addGenConstrIndicator(
                        is_root_node[net, pos_i], False,
                        #cap_i[net, pos_i] == -indicator_i_vars[net, pos_i] + 2 * s_i[net, pos_i],
                        cap_i[net, pos_i] == indicator_i_vars[net, pos_i],
                        name=f"t_definition_non_root_{net}_{pos_i}"
                    )
                else:
                    model.addConstr(cap_i[net, pos_i] == 0, name=f"middle_node_{net}_{pos_i}")
                model.addConstr(
                    net_flow[net, pos_i] == cap_i[net, pos_i],
                    name=f"flow_conservation_{net}_{pos_i}"
                )

if routing_switch == 'on':
    # Prevent different nets from using the same via position
    for v in via_indices:
        model.addConstr(gp.quicksum(v_n_v[net][v] for net in total_nets if net not in power_net) <= 1,name=f"via_conflict_{v}")
    # Prevent different nets from using the same row selection
    # Prevent consecutive row usage
    for edge in Edges_m0:
        i, j = edge
        j_prefix, j_num = j.split('_')[0], int(j.split('_')[1])
        if j_prefix == 'middle':
            target_rows = [middle_row]
        elif j_prefix == 'pv':
            target_rows = pmos_rows
        elif j_prefix == 'nv':
            target_rows = nmos_rows
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
        j_prefix, j_num = j.split('_')[0], int(j.split('_')[1])
        if not j.startswith('pv_') and j.startswith('nv_') and j.startswith('middle_'):
            for r in upper_rows:
                model.addConstr(gp.quicksum(y_n_c_r[net][i,j,r] for net in total_nets if net not in power_net)<= 1,name=f"row_selection_conflict_{i}_{j}_{r}")

    # Track cost constraints per row
    for c in columns:
        for r in rows:
            model.addConstr(
                t_c_r[c, r] == gp.quicksum(t_n_c_r[net][c, r] for net in total_nets if net not in power_net),
                name=f"track_cost_{c}_{r}"
            )
            model.addConstr(
                t_c_r[c, r] + t_n_c_r[new_net_name][c, r] <= 1,
                name=f"max_track_{c}_{r}"
            )
        for r in upper_rows:
            model.addConstr(
                ut_c_r[c, r] == gp.quicksum(ut_n_c_r[net][c, r] for net in total_nets if net not in power_net),
                #ut_c_r[c, r] == gp.quicksum(ut_n_c_r[net][c, r] for net in new_nets),
                name=f"uppertrack_cost_{c}_{r}"
            )
            model.addConstr(
                ut_c_r[c, r] + ut_n_c_r[new_net_name][c, r]  <= 1,
                name=f"max_uppertrack_{c}_{r}"
            )
    
    # cell-flex
    # horizontal pin separation -> horizontal pin extendability
    signal_nets = [net for net in io_pins if net not in power_net]
    pin_interruption = 2
    pin_extend_reward={}
    one_pin_net_binary={}
    cond = {}
    M = 20
    search_columns = [c for c in gate_cols if 1 <= c and c <= len(columns)-2]
    for c in search_columns:
        extendability = model.addVar(vtype=gp.GRB.BINARY, name=f"l_e_{c}")
        neighbor_cols = [c + dc for dc in range(-pin_interruption, pin_interruption+1) if 0 <= c + dc < len(columns)]
        #print(c,neighbor_cols)
        pin_extend_reward[c] = model.addVar(vtype=gp.GRB.INTEGER, name=f"p_e_r_{c}")
        cond[c]={}
        one_pin_net_binary[c]={}
        for r in rows:
            row_metal = gp.quicksum(t_n_c_r[net][ni,r] for net in total_nets if net not in power_net for ni in neighbor_cols)
            for s_n in signal_nets:
                cond[c][r, s_n] = model.addVar(vtype=gp.GRB.BINARY,name=f"cond_col{c}_row{r}_net{s_n}")
                pin_metal = gp.quicksum(t_n_c_r[s_n][ni,r] for ni in neighbor_cols)
                one_pin_net_binary[c][s_n] = model.addVar(vtype=gp.GRB.BINARY, name=f"one_pin_net_bin_{s_n}")
                pin_is_there = model.addVar(vtype=GRB.BINARY, name=f"pin_is_there_{r}_{s_n}")
                
                model.addConstr(sum_actives_vars[s_n] <= 1 + M * (1-one_pin_net_binary[c][s_n]),name=f"via_used_binary_upper")
                model.addConstr(sum_actives_vars[s_n] >= 2 - M * one_pin_net_binary[c][s_n],name=f"via_used_binary_lower")
                model.addConstr(cond[c][r,s_n] <= one_pin_net_binary[c][s_n],name=f"cond_via_{c}_{r}_{s_n}")

                model.addConstr(cond[c][r,s_n] <= pin_metal,name=f"cond_pinmetal_{c}_{r}_{s_n}")
                model.addConstr(pin_is_there <= pin_metal,name=f"pin_is_there1_pinmetal_{c}_{r}_{s_n}")
                model.addConstr(pin_is_there >= pin_metal/len(neighbor_cols),name=f"pin_is_there2_pinmetal_{c}_{r}_{s_n}")

                model.addConstr(row_metal - pin_metal <= M*(1-cond[c][r,s_n]),name=f"cond_upper_{c}_{r}_{s_n}")
                model.addConstr(row_metal - pin_metal >= one_pin_net_binary[c][s_n] + pin_is_there - 1 - cond[c][r,s_n],name=f"cond_lower_{c}_{r}_{s_n}")

        model.addConstr(pin_extend_reward[c]==gp.quicksum(cond[c][r,s_n] for r in rows for s_n in signal_nets),name=f"reward_make_for_{c}")

    # vertical pin separation
    z_dict = {}  # dictionary - z_{c,net1,net2,r1,r2}
    if len(gate_cols)<2: #INV_X1 special handling
        V_gate_cols = gate_cols + gate_cols
    else :
        V_gate_cols = gate_cols
    for c in V_gate_cols[:-1]:
        #pos_p = f"pp_{3 + 3 * c}"
        #pos_n = f"nn_{3 + 3 * c}"
        pos_a = f"ac_{3 + 3 * c}"
        #j_list = [pos_p,pos_n,pos_a]
        #pos_p_next = f"pp_{3 + 3 * (c+1)}"
        #pos_n_next = f"nn_{3 + 3 * (c+1)}"
        pos_a_next = f"ac_{3 + 3 * (c+2)}"
        if len(gate_cols) < 2 : #INV_X1 special handling
            pos_a_next = f"ac_{3 + 3 * (c+1)}"
        #j_list_next = [pos_p_next,pos_n_next,pos_a_next]
        for net1 in signal_nets:
            for net2 in signal_nets:
                if net1 == net2:
                    continue
                for r1 in rows:
                    for r2 in rows:
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
    for r in upper_rows:
        obs_misalign_penalty[r] = model.addVar(vtype=gp.GRB.BINARY, name=f"o_m_p_{r}")
        model.addConstr(obs_misalign_penalty[r] <= gp.quicksum(ut_n_c_r[net][c,r] for net in total_nets if net not in io_pins for c in columns) ,name=f"o_m_p_constr1_{r}")
        for net in total_nets:
            if net not in io_pins:
                for c in columns:
                    model.addConstr(obs_misalign_penalty[r] >= ut_n_c_r[net][c,r] ,name=f"o_m_p_constr2_{net}_{c}_{r}")

    # Total track cost per column
    for c in columns:
        model.addConstr(
            ut_c[c] == gp.quicksum(ut_c_r[c, r] for r in upper_rows),
            name=f"uppertrack_cost_{c}"
        )
        model.addConstr(
            t_c[c] == gp.quicksum(t_c_r[c, r] for r in rows),
            name=f"track_cost_{c}"
        )
        model.addConstr(
            t_c[c] <= MAX_TRACK,
            name=f"max_track_{c}"
        )

    # Objective function
    via_cost = 60
    via_pdn_cost = 100
    lowertrack_cost = 3
    uppertrack_cost = 6
    eol_cost = 1
    #total_via_cost = via_cost * gp.quicksum(v_n_v[net][v]  for net in total_nets if net not in power_net for v in via_indices)
    total_via_cost = via_cost * gp.quicksum(v_n_v[net][v]  for net in total_nets if net not in power_net for v in via_indices if 4*(v+1) % 3 !=0) + via_pdn_cost * gp.quicksum(v_n_v[net][v]  for net in total_nets if net not in power_net for v in via_indices if 4*(v+1) % 3 ==0)
    #total_via_cost = via_cost * gp.quicksum(v_n_v[net][v] for net in new_nets for v in valid_via_indices[net])
    total_track_cost = lowertrack_cost * gp.quicksum(t_c[c] for c in columns)
    total_uppertrack_cost = 2 * uppertrack_cost * gp.quicksum(ut_c[c] for c in columns)
    total_eol_cost = eol_cost * gp.quicksum(t_n_c_r[new_net_name][c,r] for c in columns for r in rows)
    total_uppertrack_eol_cost = eol_cost * uppertrack_cost * gp.quicksum(ut_n_c_r[new_net_name][c,r] for c in columns for r in upper_rows)

    # Cell-Flex
    # penalty
    o_m_p_cost = 100
    obs_penalty_1 = o_m_p_cost * gp.quicksum(obs_misalign_penalty[r] for r in upper_rows)
    # reward
    p_e_cost = 1
    pin_extendability = p_e_cost*gp.quicksum(pin_extend_reward[c] for c in search_columns)
    p_s_cost = 1
    pin_separation = p_s_cost*gp.quicksum(z_dict[idx] for idx in z_dict)

    model.setObjective(total_track_cost + total_via_cost + total_uppertrack_cost + total_eol_cost + total_uppertrack_eol_cost + obs_penalty_1 - pin_extendability - pin_separation ,gp.GRB.MINIMIZE)

if routing_switch == 'off':
    model.setObjective(
        gp.quicksum(flow_estimator[c] for c in gate_cols),
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
        net: [(1,via_positions[v]) for v in via_indices if v_n_v[net][v].X > 0.5] for net in total_nets if net not in power_net
    }
    eol = {}
    for c in columns:
        eol[c]=0
        for r in rows:
            eol[c] = eol[c] + t_n_c_r[new_net_name][c,r].X
    column_track_costs = {column_positions[c]: (t_c[c].X+eol[c]) for c in columns}
    sorted_column_positions = sorted(column_track_costs.keys())
    best_track_cost_list = [int(column_track_costs[c_pos]) for c_pos in sorted_column_positions]

    for i,t in enumerate(top_trans):
        for c in gate_cols:
            for o in [0,1]:
                if c_top[(i,c,o)].X > 0.5:
                    print(f"Top: {t[0]} placed at column {c}, orientation={o}")

    for j,t in enumerate(bot_trans):
        for c in gate_cols:
            for o in [0,1]:
                if c_bot[(j,c,o)].X > 0.5:
                    print(f"Bottom: {t[0]} placed at column {c}, orientation={o}")

    pmos_columns = [None]*num_cols
    nmos_columns = [None]*num_cols
    
    for c in range(num_cols):
        for net in unique_pmos_nets:
            if pmos_net[(net,c)].X > 0.5:
                pmos_columns[c] = net
        for net in unique_nmos_nets:
            if nmos_net[(net,c)].X > 0.5:
                nmos_columns[c] = net

    pr ("PMOS: 1 ",pmos_columns)
    pr ("NMOS: 1 ",nmos_columns)
    for key, var in indicator_i_vars.items():
        net, pos_i = key
        var_value = var.X
        var_value_root = is_root_node[net,pos_i].X
        if var_value > 0:
            print(f"{pos_i} is active for {net}")
        if var_value_root > 0:
            print(f"Root node of {net} is {pos_i}")
    for key, var in sum_actives_vars.items():
        net = key
        var_value = var.getValue()
        if var_value != 0:
            print(f"{net} sum active vars = {var_value}")
    if routing_switch == 'on':
        for net in total_nets:
            if net not in power_net:
                for key, var in f_n_c_r[net].items():
                    pos_i, pos_j, r = key
                    var_value = var.X
                    if var_value != 0:
                        print (f"{net} flow m0 {pos_i},{pos_j},{r} : {var_value}")
                for key, var in f_n_c_ur[net].items():
                    pos_i, pos_j, r = key
                    var_value = var.X
                    if var_value != 0:
                        print (f"{net} flow m2 {pos_i},{pos_j},{r} : {var_value}")
        for key, var in cap_i.items():
            net, pos_i = key
            var_value = var.X
            if var_value != 0:
                print(f"{net}'s net flow(in-out) of {pos_i} is {int(var_value)} / Detail {var_value}")

    if routing_switch == 'on':
        pr("\nt_n_c_r and ut_n_c_r values:")
        for net in total_nets:
            if net not in power_net:
                pr(f"  Net {net}: Via positions {best_via_locations.get(net, [])}, []")
                for r in rows:
                    c_t_c = {column_positions[c]: t_n_c_r[net][c, r].X for c in columns}
                    s_c_p = sorted(c_t_c.keys())
                    b_t_c_l = [int(round(c_t_c[c_pos])) for c_pos in s_c_p]
                    pr(f"  Net {net}, H 1, Row {r}: {b_t_c_l}")
                for r in upper_rows:
                    c_ut_c = {column_positions[c]: ut_n_c_r[net][c, r].X for c in columns}
                    s_c_p = sorted(c_ut_c.keys())
                    b_ut_c_l = [round(int(c_ut_c[c_pos])) for c_pos in s_c_p]
                    pr(f"  Net {net}, H 1, Row {r}: {b_ut_c_l}")
        for r in rows:
            c_t_c = {column_positions[c]: t_n_c_r[new_net_name][c, r].X for c in columns}
            s_c_p = sorted(c_t_c.keys())
            b_t_c_l = [int(c_t_c[c_pos]) for c_pos in s_c_p]
            pr(f"  Net {new_net_name}, Row {r}: {b_t_c_l}")
        for r in upper_rows:
            c_t_c = {column_positions[c]: ut_n_c_r[new_net_name][c, r].X for c in columns}
            s_c_p = sorted(c_t_c.keys())
            b_t_c_l = [int(c_t_c[c_pos]) for c_pos in s_c_p]
            pr(f"  Net {new_net_name}, Row {r}: {b_t_c_l}")

        # Results
        pr(f"\nOptimal total cost: {total_cost}")
        pr("Optimal Via positions:")
        for net in total_nets:
            if net not in power_net:
                pr(f"  Net {net}: Via positions {best_via_locations.get(net, [])}")
        pr(f"Column Track Costs: {best_track_cost_list}")
    
    for c in gate_cols:
        print (f"Column : {c}, {a_c[c].X}, {b_c[c].X}, {misalign_c[c].X}, {e_c[c].getValue()}")
else:
    pr("No optimal solution found.")

pr ("Runtime : ",round(end_time-start_time,3))
