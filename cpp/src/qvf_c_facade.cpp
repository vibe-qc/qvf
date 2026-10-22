// Complete C facade; no C++ exception crosses this boundary. License: Apache-2.0.
#include "qvf_c_internal.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
namespace qvf_c_detail {
thread_local Error global_error;
qvf::DType dtype(qvf_dtype d) {
    require(d >= QVF_INT8 && d <= QVF_FLOAT64, "invalid dtype");
    return static_cast<qvf::DType>(static_cast<int>(d) - 1);
}
qvf_dtype dtype(const std::string& d) {
    static const char* names[] = {"int8","int16","int32","int64","uint8","uint16","uint32","uint64","float32","float64"};
    for (size_t i=0; i<10; ++i) if (d == names[i]) return static_cast<qvf_dtype>(i+1);
    throw std::invalid_argument("invalid member dtype");
}
std::vector<int64_t> shape(size_t rank, const int64_t* dims) {
    require(rank <= 64, "rank exceeds 64"); require(!rank || dims, "NULL shape");
    return rank ? std::vector<int64_t>(dims,dims+rank) : std::vector<int64_t>{};
}
qvf::TensorData tensor(const qvf_tensor_view* in) {
    require(in, "NULL tensor"); require(in->byte_order >= QVF_NATIVE && in->byte_order <= QVF_BIG_ENDIAN, "invalid byte order");
    qvf::TensorView v(in->data,dtype(in->dtype),shape(in->rank,in->shape),static_cast<qvf::ByteOrder>(in->byte_order));
    require(v.byte_size() == in->data_bytes, "tensor data_bytes differs from dtype/shape");
    require(!in->data_bytes || in->data, "NULL tensor data");
    qvf::TensorData t(v); if (in->output_dtype != QVF_DTYPE_UNKNOWN) t.output_dtype = dtype(in->output_dtype);
    return t;
}
qvf::Limits limits(const qvf_limits* p) {
    if (!p) return {};
    require(std::isfinite(p->max_ratio) && p->max_ratio >= 0, "invalid max_ratio");
    return {p->max_member_bytes,p->max_total_bytes,p->max_ratio,p->ratio_exempt_bytes,p->max_json_bytes,p->max_json_depth};
}
qvf::validate::Level level(qvf_validation_level v) {
    require(v >= QVF_VALIDATE_CONTAINER && v <= QVF_VALIDATE_ALL, "invalid validation level");
    return static_cast<qvf::validate::Level>(v);
}
qvf::ValidationOptions options(int schema) { qvf::ValidationOptions o; o.schema_check = schema != 0; return o; }
qvf::Json json(const char* s) { return qvf::Json::parse(required(s)); }
qvf::Section section(const char* s, const char* expected = nullptr) {
    auto j = json(s);
    require(j.is_object(), "section_json must be an object");
    require(!j.has("members"), "section_json must omit members");
    if (expected) {
        require(!j.has("kind") || (j.at("kind").is_string() && j.at("kind").as_string()==expected), "section kind differs from named entry point");
        j.set("kind",expected);
    }
    return qvf::Section::from_json(j);
}
qvf::OpaquePayload opaque(const qvf_opaque_input* p) {
    require(p, "NULL opaque input"); require(!p->size || p->data, "NULL opaque data");
    qvf::OpaquePayload out; out.role = required(p->role);
    if (p->size) { const auto* b = static_cast<const uint8_t*>(p->data); out.bytes.assign(b,b+p->size); }
    if (p->media_type) out.media_type = p->media_type;
    return out;
}
void add(qvf_writer* w, const qvf_section_input* p, const char* kind = nullptr) {
    require(p, "NULL section input");
    require(!p->json_count || p->json, "NULL JSON payloads"); require(!p->binary_count || p->binary,"NULL binary payloads");
    require(!p->opaque_count || p->opaque,"NULL opaque payloads");
    auto s = section(p->section_json,kind);
    std::vector<qvf::JsonPayload> j; std::vector<qvf::BinaryPayload> b; std::vector<qvf::OpaquePayload> o;
    for(size_t i=0;i<p->json_count;++i) j.push_back({required(p->json[i].role),json(p->json[i].json)});
    for(size_t i=0;i<p->binary_count;++i) b.push_back({required(p->binary[i].role),tensor(&p->binary[i].tensor)});
    for(size_t i=0;i<p->opaque_count;++i) o.push_back(opaque(&p->opaque[i]));
    w->facade().add_payload(std::move(s),j,b,o);
}
const qvf::Section& section(qvf_reader* r, const char* id) {
    const auto* s = r->impl.section(required(id)); require(s,"section not found"); return *s;
}
const qvf::Section& section(qvf_reader* r, size_t index) {
    const auto& s = r->impl.manifest().sections; require(s && index<s->size(),"section index out of range"); return s->at(index);
}
const qvf::MemberSpec& member(qvf_reader* r, const char* id, const char* role) {
    const auto* m = section(r,id).member(required(role)); require(m,"member not found"); return *m;
}
void text(qvf_reader* r, qvf::Json value, const char** out, size_t* n) {
    require(out && n,"NULL text output"); r->text = value.dump(2); *out=r->text.c_str(); *n=r->text.size();
}
void single_json(qvf_writer* w,const char* id,const char* kind,const char* role,const char* value) {
    qvf::Section s; s.id=required(id); s.kind=kind;
    w->facade().add_payload(std::move(s),{{role,json(value)}},{});
}
void finish(qvf_writer* w) {
    require(!w->editor,"editor writer must be committed through editor_commit");
    require(!w->member,"binary member still open");
    if (w->finished) return;
    if (w->legacy_mode) { w->cached_bytes=w->backend().to_bytes(); w->bytes_ready=true; }
    else w->facade().finish();
    w->finished=true;
}
} // namespace qvf_c_detail
using namespace qvf_c_detail;
extern "C" {
unsigned qvf_abi_version(void) { return QVF_ABI_VERSION; }
const char* qvf_toolkit_version(void) {
#ifdef QVF_TOOLKIT_VERSION
    return QVF_TOOLKIT_VERSION;
#else
    return "unknown"; // non-CMake builds must supply QVF_TOOLKIT_VERSION
#endif
}
const char* qvf_global_error(void) { return global_error.c_str(); }
const char* qvf_reader_last_error(const qvf_reader* r) { return r?r->last_error.c_str():"NULL reader"; }
const char* qvf_editor_last_error(const qvf_editor* e) { return e?e->last_error.c_str():"NULL editor"; }
const char* qvf_report_last_error(const qvf_report* r) { return r?r->last_error.c_str():"NULL report"; }
qvf_status qvf_limits_default(qvf_limits* out) { return protect(global_error,[&]{ require(out,"NULL limits output"); qvf::Limits d; *out={d.max_member_bytes,d.max_total_bytes,d.max_ratio,d.ratio_exempt_bytes,d.max_json_bytes,d.max_json_depth}; }); }
qvf_status qvf_writer_create(const char* p,const char* v,const char* c,const char* path,qvf_writer** out) {
    if(out) *out=nullptr;
    return protect(global_error,[&]{ require(out,"NULL writer output"); qvf::Source s{p?p:"",v?v:"",c?c:""};
        auto f=path?std::make_unique<qvf::Writer>(std::move(s),std::string(path)):std::make_unique<qvf::Writer>(std::move(s));
        *out=new qvf_writer(std::move(f)); });
}
qvf_status qvf_writer_create_callback(const char* p,const char* v,const char* c,qvf_chunk_callback cb,void* user,qvf_writer** out) {
    if(out) *out=nullptr;
    return protect(global_error,[&]{ require(out && cb,"NULL writer output/callback");
        auto sink=std::make_unique<qvf::container::CallbackSink>([=](const uint8_t* b,size_t n){ if(cb(b,n,user)) throw Cancelled{}; });
        *out=new qvf_writer(std::make_unique<qvf::Writer>(qvf::Source{p?p:"",v?v:"",c?c:""},std::move(sink))); });
}
qvf_status qvf_writer_destroy(qvf_writer* w) { delete w; return QVF_OK; }
qvf_status qvf_writer_finish(qvf_writer* w) { return guard(w,[&]{finish(w);}); }
qvf_status qvf_writer_bytes(qvf_writer* w,const void** out,size_t* n) { return guard(w,[&]{
    require(out && n,"NULL bytes output"); require(!w->editor,"editor writer has no byte output"); require(!w->member,"binary member still open");
    if (!w->bytes_ready) { if(w->legacy_mode) finish(w); else { w->cached_bytes=w->owned->to_bytes(); w->finished=true; w->bytes_ready=true; } }
    *out=w->cached_bytes.data(); *n=w->cached_bytes.size(); }); }
qvf_status qvf_writer_set_root_json(qvf_writer* w,qvf_root_block b,const char* s) { return guard(w,[&]{require(b>=QVF_ROOT_PROVENANCE && b<=QVF_ROOT_EXTENSIONS,"invalid root block"); w->facade().set_root(static_cast<qvf::RootBlock>(b),json(s));}); }
qvf_status qvf_writer_set_auto_metadata(qvf_writer* w,int b) {return guard(w,[&]{w->facade().set_auto_metadata(b!=0);});}
qvf_status qvf_writer_set_force_zip64(qvf_writer* w,int b) {return guard(w,[&]{w->facade().set_force_zip64(b!=0);});}
qvf_status qvf_writer_add_section(qvf_writer* w,const qvf_section_input* p) {return guard(w,[&]{add(w,p);});}
qvf_status qvf_writer_declare_section(qvf_writer* w,const char* p) {return guard(w,[&]{w->facade().add_section(section(p));});}
qvf_status qvf_writer_add_json(qvf_writer* w,const char* id,const char* role,const char* s) {return guard(w,[&]{w->facade().add_json(required(id),required(role),json(s));});}
qvf_status qvf_writer_add_opaque(qvf_writer* w,const char* id,const qvf_opaque_input* p) {return guard(w,[&]{w->facade().add_opaque(required(id),opaque(p));});}
qvf_status qvf_writer_begin_binary(qvf_writer* w,const char* id,const char* role,qvf_dtype d,size_t rank,const int64_t* dims) {return guard(w,[&]{ require(!w->member,"binary member already open"); w->member.emplace(w->facade().begin_binary(required(id),required(role),dtype(d),shape(rank,dims)));});}
qvf_status qvf_writer_write(qvf_writer* w,const void* p,size_t n) {return guard(w,[&]{ require(w->member.has_value(),"no open binary member"); require(!n || p,"NULL binary bytes"); w->member->write(static_cast<const uint8_t*>(p),n);});}
qvf_status qvf_writer_end_binary(qvf_writer* w) {return guard(w,[&]{ require(w->member.has_value(),"no open binary member"); w->member->close(); w->member.reset();});}
qvf_status qvf_writer_abort_binary(qvf_writer* w) {return guard(w,[&]{w->member.reset();});}
qvf_status qvf_writer_set_section_field_json(qvf_writer* w,const char* id,const char* key,const char* value) {return guard(w,[&]{w->backend().set_section_field(required(id),required(key),json(value));});}
qvf_status qvf_writer_add_structure(qvf_writer* w,const char* id,size_t n,const char* const* symbols,const int* z,const double* xyz,const int pbc[3],const double lattice[9],const char* bonds) {return guard(w,[&]{
    require(n<=static_cast<size_t>(INT64_MAX/3),"atom count too large"); require(!n || (symbols && z && xyz),"structure needs symbols, atomic_numbers and positions");
    qvf::Json atoms=qvf::Json::array(), flags=qvf::Json::array(), payload=qvf::Json::object();
    for(size_t i=0;i<n;++i){auto a=qvf::Json::object(), pos=qvf::Json::array(); for(size_t k=0;k<3;++k)pos.push_back(xyz[3*i+k]); a.set("symbol",required(symbols[i])).set("atomic_number",z[i]).set("position",pos); atoms.push_back(a);}
    for(size_t k=0;k<3;++k){require(!pbc || pbc[k]==0 || pbc[k]==1,"pbc must contain 0/1"); flags.push_back(pbc && pbc[k]!=0);}
    payload.set("atoms",atoms).set("pbc",flags);
    if(lattice){auto rows=qvf::Json::array(); for(size_t i=0;i<3;++i){auto row=qvf::Json::array();for(size_t j=0;j<3;++j)row.push_back(lattice[i*3+j]);rows.push_back(row);}payload.set("lattice_vectors",rows);}
    qvf::Section s;s.id=required(id);s.kind="structure";std::vector<qvf::JsonPayload> members{{"structure",payload}};if(bonds)members.push_back({"bonds",json(bonds)});
    w->facade().add_payload(std::move(s),members,{}); });}
#define QVF_C_KIND(name, kind) qvf_status qvf_writer_add_##name(qvf_writer* w,const qvf_section_input* p) {return guard(w,[&]{add(w,p,kind);});}
#include "qvf/c_kinds_generated.h"
#undef QVF_C_KIND
qvf_status qvf_writer_add_volume(qvf_writer* w,const char* kind,const qvf_section_input* p) {return guard(w,[&]{std::string k=required(kind);require(k.rfind("volume.",0)==0,"expected volume kind");add(w,p,kind);});}
qvf_status qvf_writer_add_spectrum_json(qvf_writer* w,const char* kind,const qvf_section_input* p) {return guard(w,[&]{std::string k=required(kind);require(k.rfind("spectra.",0)==0,"expected spectrum kind");add(w,p,kind);});}
qvf_status qvf_writer_add_spectrum_xy(qvf_writer* w,const char* kind,const char* id,size_t n,const double* x,const double* y,const char* xu,const char* yu) {return guard(w,[&]{require(!n || (x && y),"NULL spectrum arrays");qvf::Spectrum s;if(n){s.frequencies.assign(x,x+n);s.intensities.assign(y,y+n);}if(xu)s.x_units=xu;if(yu)s.y_units=yu;w->backend().add_spectrum(required(kind),s,"",required(id));});}
qvf_status qvf_writer_add_wavefunction_gto_unrestricted(qvf_writer* w,const qvf_section_input* p) {return guard(w,[&]{require(p,"NULL section input");bool found=false;for(size_t i=0;i<p->json_count;++i){require(p->json,"NULL JSON payloads");if(std::string(required(p->json[i].role))=="mo_metadata"){auto j=json(p->json[i].json);require(j.has("spin") && j.at("spin").is_string() && j.at("spin").as_string()=="unrestricted","expected unrestricted mo_metadata");found=true;}}require(found,"missing mo_metadata");add(w,p,"wavefunction.gto");});}
qvf_status qvf_writer_set_ecp_json(qvf_writer* w,const char* id,const char* s) {return guard(w,[&]{w->backend().set_wavefunction_ecp(required(id),json(s));});}
qvf_status qvf_writer_set_overlap(qvf_writer* w,const char* id,const qvf_tensor_view* p) {return guard(w,[&]{auto t=tensor(p);auto v=t.view();require(v.shape.size()==2,"overlap must have rank 2");qvf::Matrix m;m.rows=v.shape[0];m.cols=v.shape[1];std::vector<uint8_t> bytes;v.write_into([&](const uint8_t* b,size_t n){bytes.insert(bytes.end(),b,b+n);},qvf::DType::Float64);m.data.resize(bytes.size()/8);for(size_t i=0;i<m.data.size();++i){uint64_t bits=0;for(size_t k=0;k<8;++k)bits|=uint64_t(bytes[i*8+k])<<(8*k);std::memcpy(&m.data[i],&bits,8);}w->backend().set_wavefunction_overlap(required(id),m);});}
qvf_status qvf_writer_add_dos_coop_cohp(qvf_writer* w,const char* kind,const qvf_section_input* p) {return guard(w,[&]{std::string k=required(kind);require(k=="dos.coop" || k=="dos.cohp","expected dos.coop or dos.cohp");add(w,p,kind);});}
qvf_status qvf_writer_add_eos(qvf_writer* w,const qvf_section_input* p) {return guard(w,[&]{add(w,p,"equation_of_state");});}
qvf_status qvf_writer_add_job_spec_json(qvf_writer* w,const char* id,const char* s) {return guard(w,[&]{single_json(w,id,"job.spec","spec",s);});}
qvf_status qvf_writer_add_excited_states_json(qvf_writer* w,const char* id,const char* s) {return guard(w,[&]{single_json(w,id,"excited_states","states",s);});}
qvf_status qvf_writer_add_bond_orders_json(qvf_writer* w,const char* id,const char* s) {return guard(w,[&]{single_json(w,id,"bond_orders","bond_orders",s);});}
qvf_status qvf_writer_add_scf_history_json(qvf_writer* w,const char* id,const char* s) {return guard(w,[&]{single_json(w,id,"scf_history","iterations",s);});}
qvf_status qvf_writer_add_vendor_json(qvf_writer* w,const char* id,const char* kind,const char* role,const char* s) {return guard(w,[&]{require(std::string(required(kind)).rfind("x_",0)==0,"expected vendor kind");single_json(w,id,kind,required(role),s);});}
qvf_status qvf_writer_add_vendor_binary(qvf_writer* w,const char* id,const char* kind,const qvf_opaque_input* p) {return guard(w,[&]{require(std::string(required(kind)).rfind("x_",0)==0,"expected vendor kind");qvf::Section s;s.id=required(id);s.kind=kind;w->facade().add_payload(std::move(s),{},{},{opaque(p)});});}
qvf_status qvf_writer_set_extensions_json(qvf_writer* w,const char* s) {return qvf_writer_set_root_json(w,QVF_ROOT_EXTENSIONS,s);}
qvf_status qvf_reader_open(const char* path,const qvf_limits* lim,qvf_reader** out) {
    if(out) *out=nullptr;
    return protect(global_error,[&]{require(out,"NULL reader output");*out=new qvf_reader(qvf::Reader::open(required(path),limits(lim)));});
}
qvf_status qvf_reader_from_bytes(const void* p,size_t n,const qvf_limits* lim,qvf_reader** out) {
    if(out) *out=nullptr;
    return protect(global_error,[&]{require(out,"NULL reader output");require(!n || p,"NULL archive bytes");std::vector<uint8_t> b;if(n){const auto* begin=static_cast<const uint8_t*>(p);b.assign(begin,begin+n);}*out=new qvf_reader(qvf::Reader::from_bytes(std::move(b),limits(lim)));});
}
qvf_status qvf_reader_destroy(qvf_reader* r) {delete r;return QVF_OK;}
qvf_status qvf_reader_manifest_json(qvf_reader* r,const char** out,size_t* n) {return guard(r,[&]{text(r,r->impl.manifest_json(),out,n);});}
qvf_status qvf_reader_section_count(qvf_reader* r,size_t* n) {return guard(r,[&]{require(n,"NULL count");const auto& s=r->impl.manifest().sections;*n=s?s->size():0;});}
qvf_status qvf_reader_section_id(qvf_reader* r,size_t i,const char** out) {return guard(r,[&]{require(out,"NULL id output");const auto& s=section(r,i);require(s.id.has_value(),"section has no id");*out=s.id->c_str();});}
qvf_status qvf_reader_section_kind(qvf_reader* r,size_t i,const char** out) {return guard(r,[&]{require(out,"NULL kind output");const auto& s=section(r,i);require(s.kind.has_value(),"section has no kind");*out=s.kind->c_str();});}
qvf_status qvf_reader_section_fields_json(qvf_reader* r,const char* id,const char** out,size_t* n) {return guard(r,[&]{auto s=section(r,id);s.members.reset();text(r,s.to_json(),out,n);});}
qvf_status qvf_reader_root_json(qvf_reader* r,qvf_root_block b,const char** out,size_t* n) {return guard(r,[&]{require(b>=QVF_ROOT_PROVENANCE && b<=QVF_ROOT_EXTENSIONS,"invalid root block");const char* names[]={"provenance","metadata","viewer_defaults","thermochemistry","dipole_moment","constraints","energies","extensions"};const auto& root=r->impl.manifest_json();text(r,root.has(names[b])?root.at(names[b]):qvf::Json(nullptr),out,n);});}
qvf_status qvf_reader_section_json(qvf_reader* r,const char* id,const char** out,size_t* n) {return guard(r,[&]{text(r,section(r,id).to_json(),out,n);});}
qvf_status qvf_reader_member_count(qvf_reader* r,const char* id,size_t* n) {return guard(r,[&]{require(n,"NULL count");const auto& m=section(r,id).members;*n=m?m->size():0;});}
qvf_status qvf_reader_member_role(qvf_reader* r,const char* id,size_t i,const char** out) {return guard(r,[&]{require(out,"NULL role output");const auto& m=section(r,id).members;require(m && i<m->size(),"member index out of range");*out=m->at(i).first.c_str();});}
qvf_status qvf_reader_member_info(qvf_reader* r,const char* id,const char* role,qvf_member_info* out) {return guard(r,[&]{require(out,"NULL member info");const auto& m=member(r,id,role);require(m.format.has_value(),"missing member format");qvf_member_info i{};i.format=*m.format==qvf::MemberSpec::Format::Json?QVF_MEMBER_JSON:(m.dtype?QVF_MEMBER_BINARY:QVF_MEMBER_OPAQUE);i.dtype=m.dtype?dtype(*m.dtype):QVF_DTYPE_UNKNOWN;i.rank=m.shape?m.shape->size():0;i.shape=m.shape?m.shape->data():nullptr;i.nbytes=r->impl.member_size(section(r,id),role);i.path=m.path?m.path->c_str():nullptr;i.media_type=m.media_type?m.media_type->c_str():nullptr;*out=i;});}
qvf_status qvf_reader_read_json(qvf_reader* r,const char* id,const char* role,int verify,const char** out,size_t* n) {return guard(r,[&]{text(r,r->impl.json(section(r,id),required(role),verify!=0),out,n);});}
qvf_status qvf_reader_read_binary(qvf_reader* r,const char* id,const char* role,int verify,void* buffer,size_t capacity,size_t* needed) {return guard(r,[&]{
    require(needed,"NULL needed output");const auto& s=section(r,id);const auto& m=member(r,id,role);require(m.format && *m.format!=qvf::MemberSpec::Format::Json,"read_binary requires a binary or opaque member");
    const uint64_t n=r->impl.member_size(s,role);require(n<=SIZE_MAX,"member exceeds address space");*needed=static_cast<size_t>(n);if(!buffer)return;if(capacity<*needed)throw ShortBuffer{};
    size_t offset=0;auto sink=[&](const uint8_t* b,size_t count){require(count<=capacity-offset,"member exceeds caller buffer");std::memcpy(static_cast<uint8_t*>(buffer)+offset,b,count);offset+=count;};
    if(m.dtype)r->impl.tensor_into(s,role,sink,verify!=0);else r->impl.bytes_into(s,role,sink,verify!=0);
});}
qvf_status qvf_reader_read_binary_chunked(qvf_reader* r,const char* id,const char* role,int verify,qvf_chunk_callback cb,void* user) {return guard(r,[&]{require(cb,"NULL callback");const auto& s=section(r,id);const auto& m=member(r,id,role);require(m.format && *m.format!=qvf::MemberSpec::Format::Json,"read_binary requires a binary or opaque member");auto sink=[&](const uint8_t* b,size_t n){if(cb(b,n,user))throw Cancelled{};};if(m.dtype)r->impl.tensor_into(s,role,sink,verify!=0);else r->impl.bytes_into(s,role,sink,verify!=0);});}
qvf_status qvf_validate_path(const char* path,qvf_validation_level l,const qvf_limits* lim,int schema,qvf_report** out) {if(out)*out=nullptr;return protect(global_error,[&]{require(out,"NULL report output");*out=new qvf_report(qvf::validate::run_file(required(path),level(l),limits(lim),options(schema)));});}
qvf_status qvf_reader_validate(qvf_reader* r,qvf_validation_level l,int schema,qvf_report** out) {if(out)*out=nullptr;return guard(r,[&]{require(out,"NULL report output");*out=new qvf_report(r->impl.validate(level(l),options(schema)));});}
qvf_status qvf_report_destroy(qvf_report* r) {delete r;return QVF_OK;}
qvf_status qvf_report_ok(qvf_report* r,int* ok) {return guard(r,[&]{require(ok,"NULL ok output");*ok=r->impl.ok?1:0;});}
qvf_status qvf_report_count(qvf_report* r,size_t* n) {return guard(r,[&]{require(n,"NULL count");*n=r->impl.findings.size();});}
qvf_status qvf_report_get(qvf_report* r,size_t i,qvf_finding* out) {return guard(r,[&]{require(out,"NULL finding output");require(i<r->impl.findings.size(),"finding index out of range");const auto& f=r->impl.findings[i];*out={f.severity==qvf::Finding::Severity::Error?0:1,f.code.c_str(),f.where.c_str(),f.message.c_str()};});}
qvf_status qvf_editor_open(const char* path,int atomic,qvf_editor** out) {if(out)*out=nullptr;return protect(global_error,[&]{require(out,"NULL editor output");*out=new qvf_editor(qvf::Editor::open(required(path),atomic!=0));});}
qvf_status qvf_editor_writer(qvf_editor* e,qvf_writer** out) {if(out)*out=nullptr;return guard(e,[&]{require(out,"NULL writer output");e->state->editor.writer();*out=new qvf_writer(e->state);});}
qvf_status qvf_editor_remove_section(qvf_editor* e,const char* id) {return guard(e,[&]{e->state->editor.remove_section(required(id));});}
qvf_status qvf_editor_set_run_status(qvf_editor* e,qvf_run_status status,const char* id) {return guard(e,[&]{require(status>=QVF_RUN_RUNNING && status<=QVF_RUN_FAILED,"invalid run status");e->state->editor.set_run_status(static_cast<qvf::RunStatus>(status),id?id:"");});}
qvf_status qvf_editor_commit(qvf_editor* e) {return guard(e,[&]{e->state->editor.commit();});}
qvf_status qvf_editor_destroy(qvf_editor* e) {delete e;return QVF_OK;}
qvf_status qvf_repack(const char* in,const char* out,int deflate) {return protect(global_error,[&]{qvf::Editor::repack(required(in),required(out),deflate?qvf::container::Method::Deflate:qvf::container::Method::Store);});}
} // extern C
