// qvf_c.cpp — C ABI implementation over qvf::QvfWriter. License: Apache-2.0.
#include "qvf/qvf_c.h"

#include <exception>
#include <string>

#include "qvf/qvf.hpp"

struct qvf_writer {
    qvf::QvfWriter impl;
    std::string last_error;
    explicit qvf_writer(qvf::Source s) : impl(std::move(s)) {}
};

// Run `body`, capturing any exception into w->last_error. Returns 0/!=0.
template <typename F>
static int guard(qvf_writer* w, F&& body) {
    if (!w) return -1;
    w->last_error.clear();
    try {
        body();
        return 0;
    } catch (const std::exception& e) {
        w->last_error = e.what();
        return 1;
    } catch (...) {
        w->last_error = "unknown error";
        return 2;
    }
}

extern "C" {

qvf_writer* qvf_create(const char* program, const char* version,
                       const char* calculation) {
    try {
        qvf::Source s{program ? program : "", version ? version : "",
                      calculation ? calculation : ""};
        return new qvf_writer(std::move(s));
    } catch (...) {
        return nullptr;
    }
}

void qvf_destroy(qvf_writer* w) { delete w; }

const char* qvf_last_error(qvf_writer* w) {
    return w ? w->last_error.c_str() : "";
}

int qvf_add_structure(qvf_writer* w, const char* const* symbols,
                      const int* atomic_numbers, const double* positions,
                      int n_atoms) {
    return guard(w, [&] {
        std::vector<qvf::Atom> atoms;
        atoms.reserve(static_cast<size_t>(n_atoms));
        for (int i = 0; i < n_atoms; ++i) {
            qvf::Atom a;
            if (symbols && symbols[i]) a.symbol = symbols[i];
            if (atomic_numbers) a.atomic_number = atomic_numbers[i];
            if (positions) {
                a.position = {{positions[i * 3], positions[i * 3 + 1],
                               positions[i * 3 + 2]}};
            }
            atoms.push_back(std::move(a));
        }
        w->impl.add_structure(atoms);
    });
}

int qvf_add_wavefunction_gto(
    qvf_writer* w, int n_shells, const int* shell_center, const int* shell_l,
    const int* shell_nprim, const double* exponents_flat,
    const double* coeffs_flat, int pure, int coeffs_are_libint_normalized,
    int n_mo, int n_ao, const double* mo_coeffs, const double* energies,
    const double* occupations) {
    return guard(w, [&] {
        qvf::WavefunctionGTO wf;
        wf.pure = pure != 0;
        wf.coeffs_are_libint_normalized = coeffs_are_libint_normalized != 0;
        size_t off = 0;
        for (int s = 0; s < n_shells; ++s) {
            qvf::Shell sh;
            sh.center = shell_center[s];
            sh.l = shell_l[s];
            sh.pure = pure != 0;
            int np = shell_nprim[s];
            for (int p = 0; p < np; ++p) {
                sh.exponents.push_back(exponents_flat[off + p]);
                sh.coefficients.push_back(coeffs_flat[off + p]);
            }
            off += static_cast<size_t>(np);
            wf.shells.push_back(std::move(sh));
        }
        wf.mo_coefficients.rows = n_mo;
        wf.mo_coefficients.cols = n_ao;
        wf.mo_coefficients.data.assign(
            mo_coeffs, mo_coeffs + static_cast<size_t>(n_mo) * n_ao);
        if (energies)
            wf.energies.assign(energies, energies + n_mo);
        if (occupations)
            wf.occupations.assign(occupations, occupations + n_mo);
        w->impl.add_wavefunction_gto(wf);
    });
}

int qvf_add_spectrum_xy(qvf_writer* w, const char* kind, const double* freqs,
                        const double* intensities, int n) {
    return guard(w, [&] {
        qvf::Spectrum s;
        s.frequencies.assign(freqs, freqs + n);
        s.intensities.assign(intensities, intensities + n);
        w->impl.add_spectrum(kind, s);
    });
}

int qvf_add_spectrum_json(qvf_writer* w, const char* kind,
                          const char* spectrum_json) {
    return guard(w, [&] {
        w->impl.add_spectrum(kind, qvf::Json::raw(spectrum_json));
    });
}

int qvf_add_atom_properties(qvf_writer* w, const double* mulliken,
                            const double* loewdin, const double* spin_population,
                            int n_atoms) {
    return guard(w, [&] {
        auto vec = [&](const double* p) {
            return p ? std::vector<double>(p, p + n_atoms) : std::vector<double>{};
        };
        w->impl.add_atom_properties(vec(mulliken), vec(loewdin),
                                    vec(spin_population));
    });
}

int qvf_add_scf_history_json(qvf_writer* w, const char* iterations_json) {
    return guard(w, [&] {
        w->impl.add_scf_history(qvf::Json::raw(iterations_json));
    });
}

int qvf_add_citations(qvf_writer* w, const char* bibtex) {
    return guard(w, [&] { w->impl.add_citations(bibtex ? bibtex : ""); });
}

int qvf_add_run_record(qvf_writer* w, const char* program,
                       const char* input_text, const char* log_text,
                       const char* program_version, const char* command,
                       int has_exit_status, int exit_status,
                       const char* started_utc, const char* finished_utc,
                       int sequence) {
    return guard(w, [&] {
        qvf::RunRecord record;
        record.program = program ? program : "";
        record.input_text = input_text ? input_text : "";
        record.log_text = log_text ? log_text : "";
        record.program_version = program_version ? program_version : "";
        record.command = command ? command : "";
        record.has_exit_status = has_exit_status != 0;
        record.exit_status = exit_status;
        record.started_utc = started_utc ? started_utc : "";
        record.finished_utc = finished_utc ? finished_utc : "";
        record.sequence = sequence;
        w->impl.add_run_record(record);
    });
}

int qvf_add_job_spec(qvf_writer* w, const char* job_type,
                     const char* method, const char* basis,
                     const char* functional,
                     int has_charge, int charge, int multiplicity,
                     const int* kpoints,
                     const char* tasks_json, const char* options_json) {
    return guard(w, [&] {
        qvf::Json spec = qvf::Json::object();
        spec.set("job_type", job_type ? job_type : "");
        if (method && *method) spec.set("method", method);
        if (basis && *basis) spec.set("basis", basis);
        if (functional && *functional) spec.set("functional", functional);
        if (has_charge) spec.set("charge", charge);
        if (multiplicity >= 1) spec.set("multiplicity", multiplicity);
        if (kpoints)
            spec.set("kpoints", qvf::Json::from_ints(
                std::vector<int>(kpoints, kpoints + 3)));
        if (tasks_json && *tasks_json)
            spec.set("tasks", qvf::Json::raw(tasks_json));
        if (options_json && *options_json)
            spec.set("options", qvf::Json::raw(options_json));
        w->impl.add_job_spec(spec);
    });
}

int qvf_set_provenance_json(qvf_writer* w, const char* provenance_json) {
    return guard(w, [&] {
        w->impl.set_provenance(qvf::Json::raw(provenance_json));
    });
}

int qvf_add_vendor_section(qvf_writer* w, const char* kind, const char* role,
                           const char* payload_json, int critical) {
    return guard(w, [&] {
        qvf::Json members = qvf::Json::object();
        members.set(role, qvf::Json::raw(payload_json));
        w->impl.add_vendor_section(kind, members, critical != 0);
    });
}

int qvf_set_extensions_json(qvf_writer* w, const char* extensions_json) {
    return guard(w, [&] {
        w->impl.set_extensions(qvf::Json::raw(extensions_json));
    });
}

int qvf_write(qvf_writer* w, const char* path) {
    return guard(w, [&] { w->impl.write(path ? path : "out.qvf"); });
}

}  // extern "C"
