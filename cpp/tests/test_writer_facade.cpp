// Focused WP-42 coverage. Scratch archives live in the build directory.
// License: Apache-2.0.
#include "qvf/editor.hpp"
#include "qvf/kinds/all.hpp"
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <set>
using namespace qvf;
namespace {
int failed = 0;
void check(bool ok, const char* text) { if (!ok) { ++failed; std::cerr << "FAIL " << text << '\n'; } }
template<class F> bool throws(F&& f) { try { f(); } catch (const std::exception&) { return true; } return false; }
std::vector<uint8_t> bytes(const std::string& p) {
    std::ifstream in(p, std::ios::binary); return {std::istreambuf_iterator<char>(in), {}};
}
bool same_json(const Json& a,const Json& b) {
    if(a.is_number() && b.is_number()) return a.as_double()==b.as_double();
    if(a.type()!=b.type())return false;
    if(a.is_object()) {
        if(a.items().size()!=b.items().size())return false;
        for(const auto& kv:a.items())if(!b.has(kv.first)||!same_json(kv.second,b.at(kv.first)))return false;
        return true;
    }
    if(a.is_array()) {
        if(a.elements().size()!=b.elements().size())return false;
        for(size_t i=0;i<a.elements().size();++i)if(!same_json(a.elements()[i],b.elements()[i]))return false;
        return true;
    }
    return a.dump(0)==b.dump(0);
}
kinds::Structure structure() {
    kinds::Structure s;
    kinds::StructureAtom a; a.symbol="H"; a.position={0,0,0}; a.atomic_number=1;
    s.structure.atoms.push_back(a); a.position[2]=0.74; s.structure.atoms.push_back(a);
    s.fields.charge=0; s.fields.multiplicity=1;
    s.structure.extra["x_note"]="preserved"; return s;
}
void add_sample(Writer& w, const std::vector<double>& data) {
    w.set_auto_metadata(false); w.add(structure());
    kinds::VolumeDensity volume; volume.grid.origin={0,0,0};
    volume.grid.voxel_vectors={{{1,0,0},{0,1,0},{0,0,1}}};
    volume.grid.shape={1,1,static_cast<int64_t>(data.size())};
    volume.data=TensorView(data.data(),DType::Float64,{1,1,static_cast<int64_t>(data.size())});
    w.add(volume);
    kinds::JobSpec job; job.spec.job_type="molecular";
    job.spec.basis.emplace(std::nullopt); // explicit null, distinct from absent
    job.spec.structure_ref="structure"; w.add(job);
}
}
int main(int argc, char** argv) {
    try {
        std::vector<double> data(50000); for(size_t i=0;i<data.size();++i)data[i]=static_cast<double>(i)/3;
        Writer memory({"facade-test","1","typed"}); add_sample(memory,data);
        auto archive=memory.to_bytes();
        std::vector<uint8_t> streamed;
        Writer callback({"facade-test","1","typed"},std::make_unique<container::CallbackSink>(
            [&streamed](const uint8_t* p,size_t n){streamed.insert(streamed.end(),p,p+n);}));
        add_sample(callback,data); callback.finish(); callback.finish();
        auto a=container::ZipReader::from_bytes(archive),b=container::ZipReader::from_bytes(streamed);
        for(const auto& name:a.names()) check(a.read(name)==b.read(name),"memory and callback member bytes match");
        check(a.entries().back().name=="manifest.json","manifest is last");
        auto reader=Reader::from_bytes(std::move(archive));
        check(reader.validate().ok,"typed archive validates");
        auto atoms=reader.get<kinds::Structure>("structure");
        check(atoms.structure.atoms.size()==2 && atoms.fields.multiplicity==1,"typed structure fields");
        check(atoms.structure.extra.at("x_note").as_string()=="preserved","typed payload extensions preserved");
        auto volume=reader.get<kinds::VolumeDensity>("volume_density");
        check(volume.data.owned() && volume.data.owned()->bytes==tensor_f64(data,{1,1,50000}).bytes,"typed tensors own reader data");
        auto job=reader.get<kinds::JobSpec>("job_spec");
        check(job.spec.basis && !*job.spec.basis && !job.spec.functional,"absent and explicit null remain distinct");
        check(throws([&]{reader.get<kinds::Trajectory>("structure");}),"wrong canonical kind rejected");
        // Conversion is chunked, byte-order independent, exact for integer copies.
        auto expected=tensor_f64({1.25,-2.5,3.75},{3}); auto big=expected.bytes;
        for(size_t i=0;i<big.size();i+=8) std::reverse(big.begin()+i,big.begin()+i+8);
        TensorView view(big.data(),DType::Float64,{3},ByteOrder::Big); std::vector<uint8_t> converted;
        view.write_into([&](const uint8_t* p,size_t n){converted.insert(converted.end(),p,p+n);},DType::Float32);
        check(converted==tensor_f32({1.25,-2.5,3.75},{3}).bytes,"big-endian float64 to float32");
        size_t largest=0,total=0;
        TensorView(data.data(),DType::Float64,{50000}).write_into([&](const uint8_t*,size_t n){largest=std::max(largest,n);total+=n;});
        check(largest<=65536 && total==data.size()*8,"tensor writes bounded chunks");
        uint64_t maximum=UINT64_MAX;
        check(throws([&]{TensorView(&maximum,DType::UInt64,{1}).write_into([](const uint8_t*,size_t){},DType::Int64);}),"integer overflow refused");
        check(throws([&]{TensorView(nullptr,DType::Float64,{1}).byte_size();}),"null data refused");
        check(throws([&]{TensorView(&maximum,DType::UInt64,{INT64_MAX,INT64_MAX}).byte_size();}),"shape overflow refused");
        Writer bad({"test","1","atomic"}); bad.set_auto_metadata(false); bad.add(structure());
        check(throws([&]{bad.add(structure());}),"duplicate ID refused");
        auto wrong=structure(); wrong.id="wrong"; wrong.structure.atoms[0].symbol="";
        check(throws([&]{bad.add(wrong);}),"payload schema checked before write");
        check(bad.manifest().sections->size()==1,"invalid payload leaves no section");
        auto bz=container::ZipReader::from_bytes(bad.to_bytes());
        check(bz.names().size()==2,"invalid typed add leaves no orphan entries");
        // Conversion failure after several streamed chunks rolls back every
        // member of the new section, including JSON already written first.
        Writer rollback({"test","1","rollback"}); rollback.set_auto_metadata(false);
        Section custom; custom.id="custom"; custom.kind="x_test.tensor";
        std::vector<int64_t> integers(70000,1); integers.back()=300;
        TensorData narrowed(TensorView(integers.data(),DType::Int64,{70000})); narrowed.output_dtype=DType::UInt8;
        check(throws([&]{rollback.add_payload(custom,{{"meta",Json::object()}},{{"data",narrowed}});}),"late conversion failure throws");
        rollback.add(structure());
        auto rz=container::ZipReader::from_bytes(rollback.to_bytes());
        check(rz.names().size()==2,"late conversion failure leaves no referenced orphan");
        Writer slabs({"test","1","slabs"}); slabs.set_auto_metadata(false); slabs.add_section(custom);
        {auto sink=slabs.begin_binary("custom","data",DType::Float64,{2});double x=1;
         sink.write(&x,sizeof(x));check(throws([&]{sink.close();}),"short member close throws");}
        {auto sink=slabs.begin_binary("custom","data",DType::Float64,{2});
         const auto v=tensor_f64({1,2},{2});sink.write(v.bytes);sink.close();}
        auto slab_reader=Reader::from_bytes(slabs.to_bytes());
        check(slab_reader.tensor(*slab_reader.section("custom"),"data").bytes==tensor_f64({1,2},{2}).bytes,"abandoned member can be retried");
        // Atomic editor: abandon and commit, append, replace, status and repack.
        const std::string path="writer_facade_edit.qvf",packed="writer_facade_repacked.qvf";
        {Writer w({"test","1","editor"},path);w.set_auto_metadata(false);w.add(structure());
         kinds::RunRecord run;run.fields.program="example";run.fields.run_status="running";
         run.log=kinds::OpaqueData{{'o','k'},std::string("text/plain")};w.add(run);w.finish();}
        const auto original=bytes(path);
        {auto e=Editor::open(path,true);e.remove_section("structure");e.append(structure());
         check(bytes(path)==original,"atomic update leaves original intact before commit");}
        check(bytes(path)==original,"abandoned atomic update leaves original intact");
        {auto e=Editor::open(path,true);e.remove_section("structure");auto replacement=structure();
         replacement.structure.atoms[1].position[2]=0.8;e.append(replacement);
         e.set_run_status(RunStatus::Converged);e.commit();e.commit();}
        auto edited=Reader::open(path);
        check(edited.get<kinds::Structure>("structure").structure.atoms[1].position[2]==0.8,"editor replaces typed structure");
        check(edited.get<kinds::RunRecord>("run_record").fields.run_status=="converged","editor sets run status");
        check(edited.validate().ok,"edited archive validates (orphans are warnings)");
        Editor::repack(path,packed,container::Method::Store);
        auto packed_reader=Reader::open(packed);check(packed_reader.validate().ok,"repacked archive validates");
        auto packed_zip=container::ZipReader::open(packed);
        check(packed_zip.duplicates().empty(),"repack removes superseded manifests");
        for(const auto& entry:packed_zip.entries())check(entry.method==0,"repack honors compression method");
        // Every generated canonical decoder/encoder is exercised on a real
        // corpus section. Read each kind only once, retaining the source
        // archive's sibling sections so forward references remain resolvable.
        if(argc>1) {
            std::set<std::string> covered;
            for(const auto& f:std::filesystem::directory_iterator(argv[1])) {
                if(f.path().extension()!=".qvf")continue;
                auto r=Reader::open(f.path().string());
                if(!r.manifest().sections)continue;
                for(const auto& s:*r.manifest().sections) {
                    if(!s.kind || !s.id || covered.count(*s.kind) || !gen::kind_info(*s.kind))continue;
                    Writer w({"typed-roundtrip","1","corpus"}); w.set_auto_metadata(false);
                    kinds::copy_section(r,s,w);
                    auto out=Reader::from_bytes(w.to_bytes());
                    const Section* copy=out.section(*s.id);
                    check(copy && copy->kind==s.kind,"canonical kind roundtrip");
                    if(copy && s.members)for(const auto& member:*s.members) {
                        const auto* spec=copy->member(member.first);check(spec!=nullptr,"canonical role preserved");
                        if(!spec)continue;
                        if(member.second.format==MemberSpec::Format::Json)
                            check(same_json(r.json(s,member.first),out.json(*copy,member.first)),"typed JSON roundtrip");
                        else check(r.bytes(s,member.first)==out.bytes(*copy,member.first),"typed binary roundtrip");
                    }
                    covered.insert(*s.kind);
                }
            }
            check(covered.size()==gen::kKindCount,"every canonical kind decoded and encoded");
            std::cout << "canonical kinds covered: " << covered.size() << '\n';
        }
        std::cout << "WP-42 output for Python validation: " << path << " " << packed << '\n';
    } catch(const std::exception& e) {++failed;std::cerr<<"FAIL unexpected exception: "<<e.what()<<'\n';}
    if(!failed)std::cout<<"all Writer/Editor/typed kind tests passed\n";
    return failed?1:0;
}
