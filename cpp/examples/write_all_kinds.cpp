// write_all_kinds.cpp — emit an archive exercising every canonical QVF section
// kind plus a vendor section. Used by the cross-language parity check: the
// emitted archive is validated by python/qvf_reader.py (jsonschema). Data is
// synthetic. Run:  ./write_all_kinds out.qvf
#include <array>
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
    w.add_bonds({{0, 2, 1.0}}, "bonds", "structure");
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
    w.add_volume("volume.laplacian", grid, v32);
    w.add_volume_difference(grid, v32, dens, homo, "rho - homo");
    // vector [nx, ny, nz, 3], complex [nx, ny, nz, 2] ([re, im]) and a series
    // [n, nx, ny, nz] of two densities 0.5 fs apart (spec § 5.2)
    w.add_volume("volume.vector", grid, tensor_f32(std::vector<double>(192, 0.1), {4, 4, 4, 3}),
                 "gradient");
    w.add_volume("volume.complex", grid,
                 tensor_f64(std::vector<double>(128, 0.1), {4, 4, 4, 2}));
    Json time_axis = Json::object();
    time_axis.set("kind", "time").set("values", Json::from_doubles({0.0, 0.5}))
             .set("units", "fs");
    w.add_volume_series(grid, tensor_f32(std::vector<double>(128, 0.1), {2, 4, 4, 4}),
                        time_axis, "rho(t)");

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

    // A periodic MD trajectory (spec § 5.5): float32 coords, one cell per frame
    // in rows and Å (the structure convention), velocities, the energy gradient
    // (forces are its negative), times and temperatures.
    {
        std::vector<Lattice> cells;
        for (int k = 0; k < 5; ++k)
            cells.push_back(Lattice::from_rows_angstrom(
                {{{{9.0 + 0.01 * k, 0, 0}}, {{0.3, 9.0, 0}}, {{0.2, 0.4, 9.0}}}}));
        Json mdmeta = Json::object();
        mdmeta.set("symbols", Json::from_strings({"O", "H", "H"}))
            .set("kind", "md").set("ensemble", "npt").set("timestep_fs", 0.5)
            .set("pbc", Json::array().push_back(true).push_back(true).push_back(true));
        const Tensor md_coords = tensor_f32(coords, {5, 3, 3});
        const Tensor vel = tensor_f64(std::vector<double>(45, 0.001), {5, 3, 3});
        const Tensor grad = tensor_f64(std::vector<double>(45, 0.0), {5, 3, 3});
        const Tensor times = tensor_f64({0.0, 0.5, 1.0, 1.5, 2.0}, {5});
        const Tensor temps = tensor_f64({300, 301, 299, 300, 302}, {5});
        TrajectoryExtras md;
        md.velocities = &vel;
        md.gradient = &grad;
        md.times = &times;
        md.temperatures = &temps;
        w.add_trajectory(mdmeta, md_coords, cells, md, "md");
    }

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

    // bands (two spin channels: rank-4 fat-band projections + occupations)
    Json kpath = Json::object();
    Json kchans = Json::array();
    { Json c = Json::object();
      c.set("atom", 0).set("l", 1).set("label", "O-2p");
      kchans.push_back(c); }
    kpath.set("n_spin", 2).set("n_kpoints", 10).set("n_bands", 4)
         .set("fermi", 0.0).set("channels", kchans);
    Tensor bproj = tensor_f64(std::vector<double>(2 * 10 * 4, 0.5), {2, 10, 4, 1});
    Tensor bocc = tensor_f64(std::vector<double>(2 * 10 * 4, 1.0), {2, 10, 4});
    w.add_bands(kpath, tensor_f64(std::vector<double>(80, 0.0), {2, 10, 4}),
                &bproj, &bocc);

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
                        tensor_f64({0, 0, 0}, {1, 3}), tensor_f64({0}, {1}),
                        coopmeta);
    w.add_dos_coop_cohp("dos.cohp", tensor_f64({-1, 0, 1}, {3}),
                        tensor_f64({0, 0, 0}, {1, 3}), tensor_f64({0}, {1}),
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
         .set("tasks", Json::from_strings({"single_point"}))
         .set("structure_ref", "structure").set("dispersion", "d3bj");
    Json jscf = Json::object();
    jscf.set("convergence", 1e-8).set("max_iterations", 100);
    jspec.set("scf", jscf);
    Json jres = Json::object();      // hints, not requirements
    jres.set("n_cores", 4).set("walltime_s", 3600.0);
    jspec.set("resources", jres);
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

    // forces (energy gradient, hartree/bohr; forces = -gradient) / hessian
    // (hartree/bohr^2) / root energies block
    Json fmeta = Json::object();
    fmeta.set("structure_ref", "structure").set("method", "rhf")
         .set("convention", "gradient");
    w.add_forces(tensor_f64({0, 0, 0.02, 0, 0.01, -0.01, 0, -0.01, -0.01}, {3, 3}),
                 nullptr, fmeta);
    std::vector<double> hess(81, 0.0);
    for (size_t k = 0; k < 9; ++k) hess[k * 9 + k] = 0.5;
    Json hmeta = Json::object();
    hmeta.set("structure_ref", "structure")
         .set("atom_masses_amu", Json::from_doubles({15.999, 1.008, 1.008}));
    w.add_hessian(tensor_f64(hess, {9, 9}), hmeta);
    Json etotal = Json::object();
    etotal.set("value", -74.9629).set("units", "hartree");
    Json energies = Json::object();
    energies.set("total", etotal).set("method", "rhf");
    w.set_energies(energies);

    // excited_states with the NTO pair and the transition density of its
    // state 1 (spec § 5.2, § 5.3, § 5.12)
    for (const char* role : {"hole", "particle"}) {
        WavefunctionGTO nto = wf;
        nto.orbital_kind = "nto";
        nto.mo_coefficients = {1, 4, {0.5, 0.5, 0.5, 0.5}};
        nto.energies = {};
        nto.occupations = {1.0};
        nto.state_ref = "excited_states";
        nto.state_index = 1;
        nto.nto_role = role;
        nto.section_id = std::string("nto_") + role;
        w.add_wavefunction_gto(nto);
    }
    w.add_volume_transition_density(grid, v32, "excited_states", 1, "S1", "tden");
    w.add_excited_states(
        Json::parse(R"([{"index":1,"excitation_energy":7.4,"oscillator_strength":0.05,)"
                    R"("transition_dipole":[0.5,0,0],)"
                    R"("contributions":[{"from_mo":1,"to_mo":2,"weight":0.97}],)"
                    R"("nto_ref":"nto_hole","density_ref":"tden"}])"),
        Json::parse(R"({"method":"tddft","n_states":1})"), "wf");

    // property kinds (spec § 5.13): the electric dipole restates the root
    // dipole_moment set below; one Born tensor per atom of the 3-atom structure.
    w.add_electric_properties(Json::parse(
        "{\"origin\":\"center_of_mass\","
        "\"dipole\":{\"vector\":[0,0,1.86],\"total\":1.86,\"units\":\"debye\"},"
        "\"quadrupole\":{\"matrix\":[[1,0,0],[0,-0.5,0],[0,0,-0.5]],"
        "\"traceless\":true,\"convention\":\"buckingham\"},"
        "\"polarizability\":{\"matrix\":[[8.6,0,0],[0,9.1,0],[0,0,9.5]],"
        "\"isotropic\":9.066667}}"));
    w.add_elastic_properties(Json::parse(
        "{\"stiffness\":[[36.4,8.8,8.8,0,0,0],[8.8,36.4,8.8,0,0,0],[8.8,8.8,36.4,0,0,0],"
        "[0,0,0,8,0,0],[0,0,0,0,8,0],[0,0,0,0,0,8]],"
        "\"bulk_modulus_gpa\":18,\"average\":\"voigt\"}"));
    w.add_dielectric_properties(Json::parse(
        "{\"electronic\":[[2,0,0],[0,2,0],[0,0,2]],\"ionic\":[[1,0,0],[0,1,0],[0,0,1]],"
        "\"static\":[[3,0,0],[0,3,0],[0,0,3]],"
        "\"born_charges\":[[[-0.8,0,0],[0,-0.8,0],[0,0,-0.8]],"
        "[[0.4,0,0],[0,0.4,0],[0,0,0.4]],[[0.4,0,0],[0,0.4,0],[0,0,0.4]]]}"));

    // wavefunction.bloch (provisional, spec § 5.3.1): Bloch orbitals of a
    // periodic hydrogen chain at Gamma and X, over one s shell per atom
    w.add_structure({{"H", 1, {{0, 0, 0}}}, {"H", 1, {{0.8, 0, 0}}}},
                    {{true, false, false}},
                    {{{2.0, 0, 0}}, {{0, 10.0, 0}}, {{0, 0, 10.0}}}, {}, "chain");
    WavefunctionBloch bloch;
    bloch.shells = {Shell{0, 0, {0.4166}, {1.0}, true}, Shell{1, 0, {0.4166}, {1.0}, true}};
    bloch.structure_ref = "chain";
    bloch.kpoints = {{{0, 0, 0}}, {{0.5, 0, 0}}};
    bloch.weights = {0.5, 0.5};
    bloch.n_mo = 2;
    bloch.mo_coefficients = {0.5, 0, 0.5, 0, 0.9, 0, -0.9, 0,
                             0.6, 0.1, 0.6, -0.1, 0.8, 0.2, -0.8, 0.2};
    bloch.energies = {-0.72, 1.98, -0.58, -0.28};
    bloch.occupations = {2, 0, 2, 0};
    w.add_wavefunction_bloch(bloch);

    // chemical identity and reaction.scheme (spec § 5.1, § 5.14): water from
    // hydrogen and triplet oxygen, the species as structure sections
    const std::array<bool, 3> molecule{{false, false, false}};
    const std::vector<std::array<double, 3>> no_cell;
    w.add_structure({{"H", 1, {{0, 0, 0}}}, {"H", 1, {{0.74, 0, 0}}}}, molecule, no_cell, {},
                    "h2");
    w.add_structure({{"O", 8, {{0, 0, 0}}}, {"O", 8, {{1.21, 0, 0}}}}, molecule, no_cell, {},
                    "o2");
    w.set_structure_identity("structure", Json::parse(
        R"({"charge": 0, "multiplicity": 1, "name": "water", "smiles": "O",)"
        R"( "inchi": "InChI=1S/H2O/h1H2", "inchikey": "XLYOFNOQVPJJNP-UHFFFAOYSA-N"})"));
    w.set_structure_identity("h2", Json::parse(R"({"charge": 0, "multiplicity": 1})"));
    w.set_structure_identity("o2", Json::parse(R"({"charge": 0, "multiplicity": 3})"));
    w.set_section_field("structure", "label", "3");
    w.add_reaction_scheme(
        Json::parse(R"([{"id": "r1", "label": "a",)"
                    R"( "reactants": [{"structure_ref": "h2", "coefficient": 2}, "o2"],)"
                    R"( "products": [{"structure_ref": "structure", "coefficient": 2}],)"
                    R"( "conditions": ["spark"], "yield_percent": 100}])"),
        "water synthesis");

    // preview (spec § 5.15): a 1x1 PNG thumbnail and an SVG rendering
    const std::vector<uint8_t> png = {
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48,
        0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x02, 0x00, 0x00,
        0x00, 0x90, 0x77, 0x53, 0xde, 0x00, 0x00, 0x00, 0x0c, 0x49, 0x44, 0x41, 0x54, 0x78,
        0x9c, 0x63, 0x30, 0x48, 0x38, 0x00, 0x00, 0x02, 0x14, 0x01, 0x51, 0x7a, 0xb3, 0xac,
        0x5e, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82};
    const std::string svg =
        R"(<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">)"
        R"(<rect width="1" height="1" fill="#3060c0"/></svg>)";
    w.add_preview(png, std::vector<uint8_t>(svg.begin(), svg.end()), "scheme");

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
