from collections import defaultdict
import gurobipy as gp
from gurobipy import GRB
model = gp.Model("logic opt")

def split_sets_by_paths(pmos_list, nmos_list, start_net_pmos, start_net_nmos, end_nets,total_pmos_sd_nets=None,total_nmos_sd_nets=None):
    pmos_paths = []
    nmos_paths = []
    for end_net in end_nets:
        pmos_paths.extend(trace_paths(start_net_pmos, pmos_list, {end_net}, end_nets))
        nmos_paths.extend(trace_paths(start_net_nmos, nmos_list, {end_net}, end_nets))
    #print (f"PMOS : {pmos_paths}")
    #print (f"NMOS : {nmos_paths}")
    group_pmos = group_the_transistor_path(pmos_paths)
    group_nmos = group_the_transistor_path(nmos_paths)
    
    #print(group_pmos)
    for g_p in group_pmos:
        hierarchy = build_hierarchy(g_p, start_net_pmos, verbose=False)

    pmos_groups = organize_paths_by_hierarchy(pmos_paths, end_nets)
    nmos_groups = organize_paths_by_hierarchy(nmos_paths, end_nets)
    return pmos_groups, nmos_groups

def split_sets_by_paths_2(pmos_list, start_net_pmos, end_nets, total_sd_nets=None):
    pmos_paths = []
    for end_net in end_nets:
        pmos_paths.extend(trace_paths(start_net_pmos, pmos_list, {end_net}, end_nets))
    group_pmos = group_the_transistor_path(pmos_paths)
    #print(group_pmos)
    all_hierarchies = {}
    #print(group_pmos)
    for i, g_p in enumerate(group_pmos):
        sub_h = build_hierarchy(g_p, start_net_pmos, verbose=False)
        all_hierarchies[i] = sub_h
    return all_hierarchies

def trace_paths(start_net, transistor_list, end_net, end_nets,exclude_path=None):
    new_end_nets = end_nets - end_net
    def dfs(current_net, path, visited):
        for transistor in transistor_list:
            #print (transistor,transistor[2],transistor[3],current_net,end_net)
            if transistor in path or transistor[2] in new_end_nets or transistor[3] in new_end_nets:
                continue
            if transistor[2] == current_net or transistor[3] == current_net:
                next_net = transistor[3] if transistor[2] == current_net else transistor[2]
                if next_net in visited or next_net == exclude_path:
                    continue
                if next_net in end_net:
                    paths.append(path + [transistor])
                else:
                    #print("go deeper")
                    dfs(next_net, path + [transistor], visited | {next_net})
        #print(current_net,end_net,paths)
    paths = []
    dfs(start_net, [], {start_net})
    #print(f"got path {paths}")
    return paths

def organize_paths_by_hierarchy(paths, end_nets):
    hierarchical_paths = {end_net: defaultdict(list) for end_net in end_nets}

    for path in paths:
        if not path:
            continue

        last_transistor = path[-1]
        end_net = last_transistor[3] if last_transistor[3] in end_nets else last_transistor[2]

        for transistor in path:
            source, drain = transistor[2], transistor[3]
            net_key = tuple(sorted([source, drain]))
            if transistor not in hierarchical_paths[end_net][net_key]:
                hierarchical_paths[end_net][net_key].append(transistor)

    return {end_net: dict(shared_groups) for end_net, shared_groups in hierarchical_paths.items()}

def group_the_transistor_path(paths):
    grouped_paths = []

    for path in paths:
        added_to_existing_group = False

        for i, group in enumerate(grouped_paths):
            existing_transistor_ids = {t[0] for p in group for t in p}

            if any(t[0] in existing_transistor_ids for t in path):
                group.append(path)
                added_to_existing_group = True
                break

        if not added_to_existing_group:
            grouped_paths.append([path])

    return grouped_paths

def extract_net_flow(path, power_start, verbose=False):
    if not path:
        return []

    first_tr = path[0]
    if len(first_tr) != 6:
        return []

    # unpack
    name, gate, s, d, bulk, size = first_tr
    net_flow = []

    if s == power_start:
        net_flow.append(s)   # e.g., 'VDD'
        net_flow.append(d)
        current_net = d
    elif d == power_start:
        net_flow.append(d)
        net_flow.append(s)
        current_net = s
    else:
        net_flow.append(s)
        net_flow.append(d)
        current_net = d

    for tr in path[1:]:
        if len(tr) != 6:
            continue
        _, _, s2, d2, _, _ = tr

        if s2 == current_net:
            net_flow.append(d2)
            current_net = d2
        elif d2 == current_net:
            net_flow.append(s2)
            current_net = s2
        else:
            pass

    if verbose:
        print("[extract_net_flow] path:", path)
        print("[extract_net_flow] net_flow:", net_flow)

    return net_flow


def get_all_net_flows(all_paths, power_start, verbose=False):

    unique_flows = []
    seen = set()

    for path in all_paths:
        flow = extract_net_flow(path, power_start, verbose=verbose)
        flow_tuple = tuple(flow)

        if flow_tuple not in seen:
            seen.add(flow_tuple)
            unique_flows.append(flow)

    return unique_flows


def find_common_nets_in_order(net_flows):
    if not net_flows:
        return []

    set_flows = [set(flow) for flow in net_flows]
    common_nets = set_flows[0].intersection(*set_flows[1:])
    reference_flow = net_flows[0]
    common_in_order = [net for net in reference_flow if net in common_nets]
    return common_in_order


def create_cuts(common_nets):
    cuts = []
    for i in range(len(common_nets) - 1):
        cuts.append((common_nets[i], common_nets[i+1]))
    return cuts


def filter_paths_for_segment(all_paths, segment, power_start, verbose=False):
    (start_net, end_net) = segment
    segment_paths = []

    for path in all_paths:
        flow = extract_net_flow(path, power_start, verbose=False)
        if start_net in flow and end_net in flow:
            idx_s = flow.index(start_net)
            idx_e = flow.index(end_net)
            if idx_s < idx_e:
                segment_paths.append(path)
    
    if verbose:
        print(f"[filter_paths_for_segment] segment={segment}, paths found={len(segment_paths)}")
    return segment_paths


def find_transistors_in_segment(path, start_net, end_net, power_start):
    flow = extract_net_flow(path, power_start, verbose=False)
    transistors_in_segment = []

    if start_net in flow and end_net in flow:
        idx_s = flow.index(start_net)
        idx_e = flow.index(end_net)
        if idx_s < idx_e:
            sub_nets = flow[idx_s:idx_e+1]
            for tr in path:
                if len(tr) != 6:
                    continue
                _, _, s, d, _, _ = tr
                if s in sub_nets and d in sub_nets:
                    transistors_in_segment.append(tr)

    return transistors_in_segment


def build_hierarchy(all_paths, power_start, level=0, verbose=False):
    net_flows = get_all_net_flows(all_paths, power_start, verbose=verbose)
    if not net_flows:
        return {}
    
    # (1) Find common nets among all net_flows
    common_nets = find_common_nets_in_order(net_flows)
    
    # If fewer than 2 common nets, cannot form segments
    if len(common_nets) < 2:
        return {}

    # (2) Create cuts
    cuts = create_cuts(common_nets)
    hierarchy = {}

    for (s_net, e_net) in cuts:
        sub_paths = []
        sub_transistors_set = set()
        for path in all_paths:
            flow = extract_net_flow(path, power_start, verbose=False)
            if (s_net in flow) and (e_net in flow):
                idx_s = flow.index(s_net)
                idx_e = flow.index(e_net)
                if idx_s < idx_e:
                    sub_range_nets = flow[idx_s : idx_e + 1]
                    path_trs_in_range = []
                    for tr in path:
                        if len(tr) == 6:
                            name, gate, s, d, bulk, size = tr
                            if s in sub_range_nets and d in sub_range_nets:
                                path_trs_in_range.append(tr)
                    if path_trs_in_range:
                        sub_transistors_set.update(path_trs_in_range)
                    sub_paths.append(path_trs_in_range)
        # Remove duplicates
        sub_paths = list(map(list, set(map(tuple, sub_paths))))
        if verbose:
            print("sub_paths:", sub_paths)

        if not sub_paths:
            continue

        max_length = max(len(p) for p in sub_paths)
        if verbose:
            print("max_length:", max_length)
        # Prepare variables for storing sub-hierarchy
        child_hierarchy = {}
        unique_transistors = list(sub_transistors_set)  # default

        if max_length <= 1:
            # No further breakdown
            child_hierarchy = {}
        else:
            # gather unique transistors and nets
            unique_transistor_dict = {}
            unique_nets = set()
            for path_tr_list in sub_paths:
                for tr in path_tr_list:
                    unique_transistor_dict[tr[0]] = tr
                    unique_nets.add(tr[2])  # source
                    unique_nets.add(tr[3])  # drain

            unique_transistors = list(unique_transistor_dict.values())
            child_hierarchy = split_sets_by_paths_2(
                unique_transistors, 
                s_net,               # treat s_net as the "start net" for next level
                {e_net},            # end nets
                unique_nets
            )

        # Build the final structure for this segment
        hierarchy[(s_net, e_net)] = {
            "transistors": unique_transistors,
            "sub_hierarchy": child_hierarchy
        }

    return hierarchy

def print_complex_hierarchy_with_depth(data, indent=0, depth=0):
    prefix = "  " * indent  # for visual indentation

    if isinstance(data, dict):
        # Go through each key-value pair
        for key, value in data.items():

            # 1) If the key is a Segment tuple
            if isinstance(key, tuple) and len(key) == 2 and all(isinstance(x, str) for x in key):
                print(f"{prefix}[depth {depth}] Segment: {key}")

                if isinstance(value, dict):
                    # Look for 'transistors' and 'sub_hierarchy'
                    transistors = value.get("transistors", [])
                    sub_h = value.get("sub_hierarchy", {})

                    if transistors:
                        print(f"{prefix}  [depth {depth}] Transistors:")
                        for t in transistors:
                            print(f"{prefix}    {t}")

                    if sub_h:
                        #print(f"{prefix}  [depth {depth}] Sub-Hierarchy:")
                        print(f"{prefix}  Sub-Hierarchy:")
                        # Recurse, incrementing indent and depth
                        print_complex_hierarchy_with_depth(sub_h, indent+1, depth+1)

                else:
                    # If value is not a dict, just print it
                    #print(f"{prefix}  [depth {depth}] {value}")
                    pass

            # 2) If the key is an integer (your 'ID Key')
            elif isinstance(key, int):
                print(f"{prefix}[depth {depth}] ID Key: {key}")
                # Recurse on the value (which should be another dict)
                print_complex_hierarchy_with_depth(value, indent+1, depth+1)

            # 3) Otherwise, just treat it as a generic key
            else:
                #print(f"{prefix}[depth {depth}] Key: {key}")
                print_complex_hierarchy_with_depth(value, indent+1, depth+1)

    else:
        # If 'data' itself is not a dict, just print it
        #print(f"{prefix}[depth {depth}] {data}")
        pass

def add_constraints_recursive(model, hierarchy_dict, network, source, drain, depth=0):
    for id_key, segments_dict in hierarchy_dict.items():
        all_segments = list(segments_dict.keys())
        all_transistors = set()

        for seg_name, seg_info in segments_dict.items():
            tr_list = seg_info.get("transistors", [])
            for tr in tr_list:
                all_transistors.add(tr)

        for seg_name in all_segments:
            if seg_name not in network:
                network[seg_name] = {}
            for tr in all_transistors:
                if tr not in network[seg_name]:
                    network[seg_name][tr] = model.addVar(
                        vtype=gp.GRB.BINARY, 
                        name=f"network_{id_key}_{seg_name}_{tr}"
                    )
                    
        for seg_name, seg_info in segments_dict.items():
            tr_list = seg_info.get("transistors", [])
            for i in range(len(tr_list)):
                for j in range(i+1, len(tr_list)):
                    tr1 = tr_list[i]
                    tr2 = tr_list[j]
                    print(f"parallel {tr1} {tr2}")
                    model.addConstr(
                        network[seg_name][tr1] - network[seg_name][tr2] == 0,
                        name=f"parallel_{id_key}_{seg_name}_{tr1}_{tr2}"
                    )
        for target_seg_name, seg_info in segments_dict.items():
            for i in range(len(all_segments)):
                segA = all_segments[i]
                transistorsA = segments_dict[segA].get("transistors", [])
                for j in range(i+1, len(all_segments)):
                    segB = all_segments[j]
                    transistorsB = segments_dict[segB].get("transistors", [])
                    for trA in transistorsA:
                        for trB in transistorsB:
                            print(f"series {target_seg_name} {trA} {trB}")
                            model.addConstr(
                                network[target_seg_name][trA] + network[target_seg_name][trB] <= 1,
                                name=f"series_{id_key}_{target_seg_name}_{trA}_{trB}"
                            )

        for tr in all_transistors:
            print(f"have to placed at once {tr} {all_segments}")
            model.addConstr(
                gp.quicksum(network[seg][tr] for seg in all_segments) == 1,
                name=f"assign_{id_key}_tr_{tr}"
            )
        source.setdefault(depth, {})
        drain.setdefault(depth, {})

        for tr in all_transistors:
            source[depth].setdefault(tr, {})
            drain[depth].setdefault(tr, {})
        for idx, seg_name in enumerate(all_segments):
            net_s, net_d = seg_name
            for tr in all_transistors:
                #print (depth,tr,seg_name)
                #print(idx,len(all_segments))
                if depth !=0 and len(all_segments) == 1:
                    #print(f"{depth} / catch {tr}")
                    for key, sub_value in source[depth-1][tr].items():
                        #print(f"{depth} {tr} {key}")
                        source[depth][tr][key] = model.addVar(vtype=gp.GRB.BINARY, name=f"source_{depth}_{tr}_{key}")
                        model.addConstr(source[depth][tr][key] <= source[depth-1][tr][key],name=f"source_follow_{depth}_{tr}_{key}") #review
                    model.addConstr(network[seg_name][tr] == gp.quicksum(source[depth][tr][key] for key, sub_value in source[depth-1][tr].items()),name=f"source_bound_{depth}_{tr}_{key}") #review
                    for key, sub_value in drain[depth-1][tr].items():
                        #print(f"{depth} {tr} {key}")
                        drain[depth][tr][key] = model.addVar(vtype=gp.GRB.BINARY, name=f"drain_{depth}_{tr}_{key}")
                        model.addConstr(drain[depth][tr][key] <= drain[depth-1][tr][key],name=f"drain_follow_{depth}_{tr}_{key}")
                    model.addConstr(network[seg_name][tr] == gp.quicksum(drain[depth][tr][key] for key, sub_value in drain[depth-1][tr].items()),name=f"drain_bound_{depth}_{tr}_{key}") #review
                elif depth !=0 and idx == 0:
                    #print("only source")
                    for key, sub_value in source[depth-1][tr].items():
                        #print(f"{depth} {tr} {key}")
                        source[depth][tr][key] = model.addVar(vtype=gp.GRB.BINARY, name=f"source_{depth}_{tr}_{key}")
                        model.addConstr(source[depth][tr][key] <= source[depth-1][tr][key],name=f"source_follow_{depth}_{tr}_{key}") #review
                    model.addConstr(network[seg_name][tr] == gp.quicksum(source[depth][tr][key] for key, sub_value in source[depth-1][tr].items()),name=f"source_bound_{depth}_{tr}_{key}") #review
                    drain[depth][tr][net_d] = model.addVar(vtype=gp.GRB.BINARY, name=f"drain_{depth}_{tr}_{net_d}")
                    model.addConstr(drain[depth][tr][net_d] == network[seg_name][tr],name=f"drain_{depth}_{seg_name}_{tr}")
                elif depth !=0 and idx == len(all_segments)-1:
                    for key, sub_value in drain[depth-1][tr].items():
                        #print(f"{depth} {tr} {key}")
                        drain[depth][tr][key] = model.addVar(vtype=gp.GRB.BINARY, name=f"drain_{depth}_{tr}_{key}")
                        model.addConstr(drain[depth][tr][key] <= drain[depth-1][tr][key],name=f"drain_follow_{depth}_{tr}_{key}")
                    model.addConstr(network[seg_name][tr] == gp.quicksum(drain[depth][tr][key] for key, sub_value in drain[depth-1][tr].items()),name=f"drain_bound_{depth}_{tr}_{key}") #review
                    source[depth][tr][net_s] = model.addVar(vtype=gp.GRB.BINARY, name=f"source_{depth}_{tr}_{net_s}")
                    model.addConstr(source[depth][tr][net_s] == network[seg_name][tr],name=f"source_{depth}_{seg_name}_{tr}")
                else:
                    #print(f"{depth} {tr} {net_s}")
                    source[depth][tr][net_s] = model.addVar(vtype=gp.GRB.BINARY, name=f"source_{depth}_{tr}_{net_s}")
                    drain[depth][tr][net_d] = model.addVar(vtype=gp.GRB.BINARY, name=f"drain_{depth}_{tr}_{net_d}")
                    model.addConstr(source[depth][tr][net_s] == network[seg_name][tr],name=f"source_{depth}_{seg_name}_{tr}")
                    model.addConstr(drain[depth][tr][net_d] == network[seg_name][tr],name=f"drain_{depth}_{seg_name}_{tr}")

        for seg_name, seg_info in segments_dict.items():
            sub_h = seg_info.get("sub_hierarchy", {})
            if sub_h:
                #add_constraints_recursive(model, sub_h, network, source, drain, final, depth=depth+1)  # have to deliver depth_s and depth_d?
                add_constraints_recursive(model, sub_h, network, source, drain, depth=depth+1)
            else:
                pass
                # # net determine
                # for tr in all_transistors:
                #     if tr not in final:
                #         final[tr] = {'source': {}, 'drain': {}}
                #     for key, sub_value in source[depth][tr].items():
                #         print (depth,tr,key)
                #         final[tr]['source'][key] = model.addVar(vtype=gp.GRB.BINARY,name=f"final_source_{depth}_{tr}_{key}")
                #         model.addConstr(final[tr]['source'][key] == source[depth][tr][key],name=f"link_source_{depth}_{tr}_{key}")
                #     for key, sub_value in drain[depth][tr].items():
                #         final[tr]['drain'][key] = model.addVar(vtype=gp.GRB.BINARY,name=f"final_drain_{depth}_{tr}_{key}")
                #         model.addConstr(final[tr]['drain'][key] == drain[depth][tr][key],name=f"link_drain_{depth}_{tr}_{key}")

def build_final_variables_and_constraints(source, drain, model):
    def get_max_depth_info(data):
        result = {}
        for depth, tr_dict in data.items():
            for tr, nets_dict in tr_dict.items():
                net_names = set(nets_dict.keys())
                if tr not in result:
                    result[tr] = {
                        'max_depth': depth,
                        'nets': net_names
                    }
                else:
                    if depth > result[tr]['max_depth']:
                        result[tr]['max_depth'] = depth
                        result[tr]['nets'] = net_names
                    elif depth == result[tr]['max_depth']:
                        result[tr]['nets'].update(net_names)
        return result

    def define_constraints(info_dict, data_dict, label, final_dict):
        for tr, val in info_dict.items():
            max_depth = val['max_depth']
            net_set   = val['nets']
            if tr not in final_dict:
                final_dict[tr] = {}
            final_dict[tr][label] = {}

            for net in net_set:
                var_name = f"final_variable_for_{tr}_{label}_{net}"
                final_var = model.addVar(
                    vtype=gp.GRB.BINARY,
                    name=var_name
                )
                constr_name = f"final_copy_{tr}_{label}_{net}"
                model.addConstr(
                    final_var == data_dict[max_depth][tr][net],
                    name=constr_name
                )
                final_dict[tr][label][net] = final_var

    max_info_source = get_max_depth_info(source)
    max_info_drain  = get_max_depth_info(drain)

    final = {}

    define_constraints(max_info_source, source, label="source", final_dict=final)

    define_constraints(max_info_drain, drain, label="drain", final_dict=final)

    return final


if __name__ == "__main__":
    print ("ilp_pnr")
