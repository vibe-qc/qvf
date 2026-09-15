// write_all_kinds.cpp — emit an archive exercising every canonical QVF section
// kind plus a vendor section. Used by the cross-language parity check: the
// emitted archive is validated by python/qvf_reader.py (jsonschema). Data is
// synthetic. Run:  ./write_all_kinds out.qvf
#include <string>
#include <vector>

#include "qvf/qvf.hpp"

int main(int argc, char** argv) {
    using namespace qvf;
    std::string out = argc > 1 ? argv[1] : "all_kinds.qvf";

    QvfWriter w({"test-code", "9.9", "all-kinds"});

    // structure / bonds / bond_orders
    w.add_structure({{"O", 8, {{0, 0, 0.117}}},
                     {"H", 1, {{0, 0.757, -0.469}}},
                     {"H", 1, {{0, -0.757, -0.469}}}},
                    {{false, false, false}}, {}, {{0, 1, 1.0}});
    w.add_bonds({{0, 2, 1.0}});
    Json bo_pairs = Json::array();
    { Json p = Json::object();
      p.set("i", 0).set("j", 1).set("order", 0.98).set("distance_ang", 0.96);
      bo_pairs.push_back(p); }
    w.add_bond_orders("mayer", bo_pairs);

    // volumes (4x4x4)
    Grid grid;
    grid.origin = {{-1, -1, -1}};
    grid.voxel_vectors = {{{{0.5, 0, 0}}, {{0, 0.5, 0}}, {{0, 0, 0.5}}}};
    std::vector<double> vol(64, 0.1);
    Tensor v32 = tensor_f32(vol, {4, 4, 4});
    Tensor v64 = tensor_f64(vol, {4, 4, 4});
    std::string dens = w.add_volume("volume.density", grid, v32, "rho");
    std::string homo = w.add_volume("volume.orbital", grid, v32, "homo", "real");
    w.add_volume("volume.spin", grid, v32);
    w.add_volume("volume.elf", grid, v32);
    w.add_volume("volume.generic", grid, v32, "custom");
    w.add_volume("volume.potential", grid, v64);
    w.add_volume("volume.rdg", grid, v32);
    w.add_volume_difference(grid, v32, dens, homo, "rho - homo");

    // basis.ao
    Json ao_meta = Json::object();
    ao_meta.set("atom_index", 0).set("atom_symbol", "O").set("shell_index", 0)
           .set("primitive_index", 0)
           .set("angular_momentum", Json::from_ints({0, 0}))
           .set("shell_type", "s").set("exponent", 130.7).set("coefficient", 0.15)
           .set("is_primitive", false).set("is_contracted", true).set("ao_index", 0);
    w.add_basis_ao(ao_meta, grid, v32);

    // wavefunction.gto (restricted)
    WavefunctionGTO wf;
    wf.shells = {{0, 0, {1.0, 0.5}, {0.6, 0.4}, true},
                 {0, 1, {1.0}, {1.0}, true}};
    wf.mo_coefficients = {4, 4, std::vector<double>(16, 0.25)};
    wf.energies = {-1, -0.5, 0.5, 1};
    wf.occupations = {2, 2, 0, 0};
    w.add_wavefunction_gto(wf);

    // atom_properties
    w.add_atom_properties({-0.7, 0.35, 0.35}, {}, {0.0, 0.0, 0.0});

    // trajectory + reaction.waypoints + reaction.path
    std::vector<double> coords(5 * 3 * 3, 0.0);
    Tensor coordsT = tensor_f64(coords, {5, 3, 3});
    Json tmeta = Json::object();
    tmeta.set("symbols", Json::from_strings({"O", "H", "H"}));
    std::string tid = w.add_trajectory(tmeta, coordsT);
    Json wp = Json::object();
    Json wplist = Json::array();
    { Json r = Json::object();
      r.set("frame_index", 0).set("label", "R").set("kind", "reactant");
      wplist.push_back(r); }
    wp.set("waypoints", wplist);
    w.add_reaction_waypoints(tid, wp);
    w.add_reaction_path(tmeta, coordsT);

    // scan.surface
    Json smeta = Json::object();
    smeta.set("axis_a_label", "r1").set("axis_b_label", "r2");
    w.add_scan_surface(smeta, tensor_f64({0, 1}, {2}), tensor_f64({0, 1}, {2}),
                       tensor_f64({0, 0, 0, 0}, {2, 2}));

    // vibrations
    Json vmeta = Json::object();
    vmeta.set("symbols", Json::from_strings({"O", "H", "H"}))
         .set("frequencies", Json::from_doubles({1595, 3657, 3756}));
    w.add_vibrations(vmeta, tensor_f64(std::vector<double>(27, 0.0), {3, 3, 3}));

    // spectra
    for (const char* k : {"spectra.ir", "spectra.raman", "spectra.uvvis",
                          "spectra.ecd", "spectra.vcd", "spectra.generic"}) {
        Spectrum s; s.frequencies = {100, 200}; s.intensities = {1, 2};
        w.add_spectrum(k, s);
    }
    Json nmr = Json::object();
    Json shifts = Json::array();
    { Json cs = Json::object();
      cs.set("atom_index", 1).set("symbol", "H").set("isotropic_shift_ppm", 4.6);
      shifts.push_back(cs); }
    nmr.set("isotope", "1H").set("reference", "TMS").set("chemical_shifts", shifts);
    w.add_spectrum("spectra.nmr", nmr);
    Json epr = Json::object();
    Json gt = Json::object();
    gt.set("principal", Json::from_doubles({2.0023, 2.0021, 2.0089}))
      .set("isotropic", 2.0044);
    epr.set("g_tensor", gt);
    Json zfs = Json::object();
    zfs.set("d_mhz", 1200.0).set("e_mhz", 30.0);
    epr.set("zero_field_splitting", zfs);
    w.add_spectrum("spectra.epr", epr);

    // bands
    Json kpath = Json::object();
    kpath.set("n_spin", 1).set("n_kpoints", 10).set("n_bands", 4);
    w.add_bands(kpath, tensor_f64(std::vector<double>(40, 0.0), {1, 10, 4}));

    // dos.total / projected / coop / cohp
    Json dmeta = Json::object();
    dmeta.set("smearing", 0.05).set("fermi_energy_ev", 0.0).set("n_spin", 1);
    w.add_dos_total(tensor_f64({-2, -1, 0, 1, 2}, {5}),
                    tensor_f64({0.1, 0.5, 1.0, 0.5, 0.1}, {5}), dmeta);
    Json pmeta = Json::object();
    Json chans = Json::array();
    { Json c = Json::object();
      c.set("atom_index", 0).set("symbol", "O").set("l", 0).set("label", "O-2s");
      chans.push_back(c); }
    pmeta.set("n_spin", 1).set("channels", chans);
    w.add_dos_projected(tensor_f64({-2, -1, 0, 1, 2}, {5}),
                        tensor_f64(std::vector<double>(5, 0.0), {1, 5}), pmeta);
    Json coopmeta = Json::object();
    coopmeta.set("pairs", Json::array());
    w.add_dos_coop_cohp("dos.coop", tensor_f64({-1, 0, 1}, {3}),
                        tensor_f64({0, 0, 0}, {1, 3}), tensor_f64({0, 0, 0}, {1, 3}),
                        coopmeta);
    w.add_dos_coop_cohp("dos.cohp", tensor_f64({-1, 0, 1}, {3}),
                        tensor_f64({0, 0, 0}, {1, 3}), tensor_f64({0, 0, 0}, {1, 3}),
                        coopmeta);

    // structure.symmetry / scf_history / citations
    Json sym = Json::object();
    sym.set("space_group", "C2v").set("point_group", "C2v");
    w.add_structure_symmetry(sym);
    Json iters = Json::array();
    { Json it = Json::object();
      it.set("iter", 1).set("energy_eh", -74.9).set("diis_error", 0.1);
      iters.push_back(it); }
    w.add_scf_history(iters);
    w.add_citations("@article{x2026, title={T}, author={A}, year={2026}}");

    // run.record — self-contained input + log of the producing run
    RunRecord rec;
    rec.program = "democode";
    rec.program_version = "1.0.0";
    rec.command = "democode water.inp";
    rec.input_text = "! RHF STO-3G\n* xyz 0 1\nO 0 0 0\nH 0 0 1\nH 0 1 0\n*\n";
    rec.log_text = "democode 1.0.0\nSCF converged in 8 iterations\n";
    rec.has_exit_status = true;
    rec.exit_status = 0;
    Json rfiles = Json::object();
    { Json fi = Json::object(); fi.set("filename", "water.inp");
      rfiles.set("input", fi); }
    { Json fl = Json::object(); fl.set("filename", "water.out");
      rfiles.set("log", fl); }
    rec.files = rfiles;
    w.add_run_record(rec);

    // job.spec — declarative specification of the requested calculation
    Json jspec = Json::object();
    jspec.set("job_type", "molecular").set("method", "rhf")
         .set("basis", "sto-3g").set("charge", 0).set("multiplicity", 1)
         .set("tasks", Json::from_strings({"single_point"}));
    w.add_job_spec(jspec);

    // fermi_surface / phonon_bands / phonon_dos / equation_of_state
    Json mesh = Json::object();
    mesh.set("nk1", 4).set("nk2", 4).set("nk3", 4).set("n_spin", 1)
        .set("fermi_energy_ev", 0.0).set("band_indices", Json::from_ints({3, 4}));
    w.add_fermi_surface(mesh, tensor_f64(std::vector<double>(4 * 4 * 4 * 2, 0.0),
                                         {4, 4, 4, 2}));
    Json qpath = Json::object();
    qpath.set("n_atoms", 2).set("n_modes", 6).set("has_eigenvectors", false);
    w.add_phonon_bands(qpath, tensor_f64(std::vector<double>(60, 10.0), {10, 6}));
    Json phmeta = Json::object();
    phmeta.set("n_atoms", 2).set("n_modes", 6);
    w.add_phonon_dos(phmeta, tensor_f64({0, 100, 200}, {3}),
                     tensor_f64({0.1, 1.0, 0.1}, {3}));
    Json fit = Json::object();
    fit.set("model", "birch_murnaghan").set("V0", 100.0).set("E0", -5.2)
       .set("B0", 74.0).set("B0_prime", 4.0);
    w.add_equation_of_state(tensor_f64({90, 100, 110}, {3}),
                            tensor_f64({-5.1, -5.2, -5.15}, {3}), fit);

    // topology.qtaim
    Json cps = Json::object();
    Json pts = Json::array();
    { Json p = Json::object();
      p.set("type", "bcp").set("position", Json::from_doubles({0.7, 0, 0}))
       .set("rho", 0.26).set("laplacian", -0.54);
      pts.push_back(p); }
    cps.set("points", pts);
    w.add_topology_qtaim(cps);

    // vendor section (x_orca.epr) + extensions governance
    // Vendor escape hatch: a genuinely non-canonical payload (EPR itself is now
    // the canonical spectra.epr kind emitted above).
    Json ext = Json::object();
    Json oe = Json::object();
    oe.set("version", "1.0").set("critical", true);
    ext.set("x_orca", oe);
    w.set_extensions(ext);
    Json custom = Json::object();
    Json frags = Json::array();
    { Json f = Json::object();
      f.set("atoms", Json::from_ints({0, 1, 2})).set("charge", -0.31);
      frags.push_back(f); }
    custom.set("fragments", frags);
    Json vendor_members = Json::object();
    vendor_members.set("data", custom);
    w.add_vendor_section("x_orca.fragment_charges", vendor_members, true);

    // root metadata
    Json thermo = Json::object();
    thermo.set("zpve_eh", 0.021).set("temperature_k", 298.15).set("pressure_atm", 1.0);
    w.set_thermochemistry(thermo);
    Json dip = Json::object();
    dip.set("total_debye", 1.86).set("vector_debye", Json::from_doubles({0, 0, 1.86}))
       .set("origin", "center_of_mass");
    w.set_dipole_moment(dip);

    std::string path = w.write(out);
    (void)path;
    return 0;
}
