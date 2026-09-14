# GT2N-Cell

Standard cell libraries for the GT2N 2nm nanosheet PDK, and the generator behind them.
`Framework/CellGen` is [SO3-Cell](https://github.com/ckchengucsd/SO3-Cell) modified to target GT2N,
adding cell geometry for 6 and 7 tracks, GT2N layer drawing, and a converter that maps ASAP7
netlists onto GT2N devices. The PDK itself, with the technology files, device models and rule
decks, is at [azadnaeemi/GT2N](https://github.com/azadnaeemi/GT2N).

## Libraries

`Enablement` holds one `.cdl`, one `.gds` and one `.lef` per library. A cell name carries the
track height, `gt2_6t_` or `gt2_7t_`, and the nanosheet width, so every name is unique across the
five libraries.

| Library | Tracks | Nanosheet | Cells | From GT2N netlists | From ASAP7 netlists |
|---|---|---|---|---|---|
| `gt2_so3cell_6t_w13_lvt` | 6 | 13nm | 82 | 62 | 20 |
| `gt2_so3cell_6t_w31_lvt` | 6 | 31nm | 85 | 62 | 23 |
| `gt2_so3cell_7t_w13_lvt` | 7 | 13nm | 68 | 57 | 11 |
| `gt2_so3cell_7t_w31_lvt` | 7 | 31nm | 63 | 63 | 0 |
| `gt2_so3cell_7t_w43_lvt` | 7 | 43nm | 86 | 62 | 24 |

The GT2N column counts cells regenerated from the original GT2N netlists, and the ASAP7 column
counts functions taken from ASAP7 and mapped onto GT2N devices. Where both sources carry a
function, the GT2N netlist is the one used. The extra routing track at 7 tracks also leaves room
for a 43nm nanosheet.

Every cell passes the GT2N 168-rule deck with zero violations and passes LVS against the source
netlist. The LEFs are extracted from the GDS with
[GDS-to-LEF](https://github.com/LeeJaKang/GDS-to-LEF), on a 42nm by 144nm site at 6 tracks and 42nm
by 168nm at 7 tracks.

## Generating cells

Needs Python 3.9, KLayout 0.30.5 and Gurobi with a licence at `GRB_LICENSE_FILE`. The first lines
of `run_cell.sh` load environment modules for one site, so edit them to match another.

```bash
cd Framework/CellGen

./run_cell.sh --cdl-name gt2_so3cell_6t_w13_lvt --cells "gt2_6t_inv_x1_w13_lvt"

# 7 tracks takes the 7-track geometry
./run_cell.sh --cdl-name gt2_so3cell_7t_w43_lvt --cells "gt2_7t_inv_x1_w43_lvt" \
    --geometry-config config/gt2n_7t_geometry.json
```

`--cdl-name` reads `Enablement/cdl/<name>.cdl`, and without `--cells` every cell in that netlist is
generated. The GDS lands in `Framework/CellGen/results/gds/`. `config/` holds the cell geometry for
6 and 7 tracks plus the solver settings, and `bin/asap7_to_gt2n.py` converts an ASAP7 CDL netlist
into GT2N subcircuits for a given track height, nanosheet width and threshold flavor. Run `./run_cell.sh --help` for the full option list.

## Citing

D. Jang, P. Kumar, M. N. H. Shazon, S. J. Ram, A. Svizhenko, V. Moroz, A. Ceyhan, N. A.
Radhakrishn, and A. Naeemi, "GT2N: An Open-Source 2nm Nanosheet PDK Enabling Multi-Width/VT
Benchmarking," in IEEE International Symposium on Circuits and Systems (ISCAS) 2026.

C.-K. Cheng, A. B. Kahng, B. Kang, S. Kang, J. Lee and B. Lin, "SO3-Cell: Standard Cell Layout
Automation Framework for Simultaneous Optimization of Topology, Placement, and Routing," in
Proceedings of the International Conference on Computer-Aided Design (ICCAD) 2025.

## License

BSD 3-Clause, see [LICENSE](LICENSE). `Framework/CellGen` derives from
[SO3-Cell](https://github.com/ckchengucsd/SO3-Cell). The cells derive from the netlists of
[GT2N](https://github.com/azadnaeemi/GT2N) and of
[ASAP7](https://github.com/The-OpenROAD-Project/asap7), both BSD 3-Clause.
