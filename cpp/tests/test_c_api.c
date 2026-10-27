/* Pure C acceptance of ABI 1, including compatibility symbols.
 * Temporary archives stay in the CTest build directory. License: Apache-2.0. */
#include "qvf/qvf_c.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if(!(x)) {fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);return 1;} }while(0)
#define OK(x) CHECK((x)==QVF_OK)
static int discard(const void* p,size_t n,void* user) {size_t* total=(size_t*)user;(void)p;*total+=n;return 0;}
static int cancel(const void* p,size_t n,void* user) {(void)p;(void)n;(void)user;return 1;}
struct bytes {unsigned char* data;size_t size;};
static int collect(const void* p,size_t n,void* user) {
    struct bytes* b=(struct bytes*)user;unsigned char* next=(unsigned char*)realloc(b->data,b->size+n);
    if(!next && n)return 1;
    b->data=next;if(n)memcpy(b->data+b->size,p,n);b->size+=n;return 0;
}
static int add_periodic(qvf_writer* w) {
    const char* symbols[]={"H","H"}; const int z[]={1,1},pbc[]={0,1,0};
    const double pos[]={0,0,0,0,0,0.74},lattice[]={5,0,0,0,5,0,0,0,5};
    return qvf_writer_add_structure(w,"structure",2,symbols,z,pos,pbc,lattice,"{\"pairs\":[{\"i\":0,\"j\":1,\"order\":1}]}");
}
static int check_valid(qvf_reader* r) {
    qvf_report* report=NULL;int ok=0;size_t count=0;
    if(qvf_reader_validate(r,QVF_VALIDATE_ALL,1,&report))return 0;
    qvf_report_ok(report,&ok);qvf_report_count(report,&count);
    if(!ok) {size_t i;for(i=0;i<count;++i){qvf_finding f;qvf_report_get(report,i,&f);fprintf(stderr,"%s %s %s\n",f.code,f.where,f.message);}}
    qvf_report_destroy(report);return ok;
}
int main(void) {
    qvf_writer* w=NULL; qvf_reader* r=NULL; qvf_editor* e=NULL; qvf_report* report=NULL;
    const void* archive=NULL;size_t size=0,n=0;const char* text=NULL;int ok=0;
    qvf_limits lim; qvf_member_info info; qvf_finding finding;
    CHECK(qvf_abi_version()==QVF_ABI_VERSION);CHECK(strlen(qvf_toolkit_version())>0);
    CHECK(qvf_writer_finish(NULL)==QVF_INVALID_HANDLE);CHECK(strstr(qvf_global_error(),"NULL"));
    OK(qvf_limits_default(&lim));CHECK(lim.max_member_bytes==((uint64_t)8<<30));
    OK(qvf_writer_create("c-test","1","periodic",NULL,&w));OK(qvf_writer_set_auto_metadata(w,0));
    OK(add_periodic(w));
    /* Typed descriptor converts big-endian float64 producer storage to f32. */
    {
        const unsigned char data[]={0x3f,0xf0,0,0,0,0,0,0,0x40,0,0,0,0,0,0,0};
        const int64_t shape[]={1,1,2};
        const qvf_json_input jsons[]={{"grid","{\"origin\":[0,0,0],\"voxel_vectors\":[[1,0,0],[0,1,0],[0,0,1]],\"shape\":[1,1,2]}"}};
        qvf_binary_input bins[]={{"data",{data,sizeof(data),QVF_FLOAT64,3,shape,QVF_BIG_ENDIAN,QVF_FLOAT32}}};
        qvf_section_input input={"{\"id\":\"density\"}",jsons,1,bins,1,NULL,0};
        OK(qvf_writer_add_volume_density(w,&input));
        CHECK(qvf_writer_add_volume_density(w,&input)!=0);CHECK(strlen(qvf_last_error(w))>0);
        /* Failure is detected before a second member is written. */
        bins[0].tensor.data_bytes=1;input.section_json="{\"id\":\"bad\"}";
        CHECK(qvf_writer_add_volume_density(w,&input)!=0);
    }
    /* Old entry points use the same streaming backend. ECP/overlap need the
       already emitted basis metadata; this used to fail for streamed JSON. */
    {
        const int c[]={0},l[]={0},np[]={1};const double ex[]={1},coeff[]={1},mo[]={1},energy[]={-0.5},occ[]={2},overlap[]={1};
        OK(qvf_add_wavefunction_gto(w,1,c,l,np,ex,coeff,1,0,1,1,mo,energy,occ));
        OK(qvf_set_wavefunction_overlap(w,"wf",1,overlap));
        OK(qvf_set_wavefunction_ecp_json(w,"wf","[]"));
    }
    OK(qvf_writer_finish(w));OK(qvf_writer_finish(w));OK(qvf_writer_bytes(w,&archive,&size));CHECK(size>0);
    { FILE* f=fopen("c-api-basis.qvf","wb");CHECK(f);CHECK(fwrite(archive,1,size,f)==size);CHECK(fclose(f)==0); }
    OK(qvf_reader_from_bytes(archive,size,&lim,&r));OK(qvf_writer_destroy(w));w=NULL;
    CHECK(check_valid(r));OK(qvf_reader_section_count(r,&n));CHECK(n==3);
    OK(qvf_reader_read_json(r,"structure","structure",1,&text,&n));CHECK(strstr(text,"lattice_vectors"));
    OK(qvf_reader_member_info(r,"density","data",&info));CHECK(info.dtype==QVF_FLOAT32 && info.rank==3 && info.nbytes==8);
    OK(qvf_reader_read_binary(r,"density","data",1,NULL,0,&n));CHECK(n==8);
    {
        unsigned char b[8]={9,9,9,9,9,9,9,9};size_t total=0;
        CHECK(qvf_reader_read_binary(r,"density","data",1,b,7,&n)==QVF_BUFFER_TOO_SMALL);CHECK(b[0]==9 && b[7]==9 && n==8);
        OK(qvf_reader_read_binary(r,"density","data",1,b,sizeof(b),&n));CHECK(b[2]==0x80 && b[3]==0x3f && b[7]==0x40);
        OK(qvf_reader_read_binary_chunked(r,"density","data",1,discard,&total));CHECK(total==8);
        CHECK(qvf_reader_read_binary_chunked(r,"density","data",1,cancel,NULL)==QVF_CANCELLED);
    }
    OK(qvf_reader_destroy(r));r=NULL;
    /* Existing archive metadata is read lazily during an update as well. */
    OK(qvf_editor_open("c-api-basis.qvf",1,&e));OK(qvf_editor_writer(e,&w));
    OK(qvf_writer_set_ecp_json(w,"wf","[]"));OK(qvf_editor_commit(e));
    OK(qvf_writer_destroy(w));w=NULL;OK(qvf_editor_destroy(e));e=NULL;
    OK(qvf_reader_open("c-api-basis.qvf",NULL,&r));CHECK(check_valid(r));OK(qvf_reader_destroy(r));r=NULL;
    remove("c-api-basis.qvf");
    /* Callback ZIP, error capture, and destruction of incomplete writers. */
    {
        struct bytes b={NULL,0};
        OK(qvf_writer_create_callback("c-test","1","callback",collect,&b,&w));OK(add_periodic(w));OK(qvf_writer_finish(w));OK(qvf_writer_destroy(w));w=NULL;
        OK(qvf_reader_from_bytes(b.data,b.size,NULL,&r));free(b.data);CHECK(check_valid(r));OK(qvf_reader_destroy(r));r=NULL;
        OK(qvf_writer_create_callback("c-test","1","cancel",cancel,NULL,&w));CHECK(add_periodic(w)==QVF_CANCELLED);OK(qvf_writer_destroy(w));w=NULL;
    }
    /* Manual member API permits retry after abort; opaque bytes round-trip. */
    OK(qvf_writer_create("c-test","1","members",NULL,&w));
    OK(qvf_writer_set_extensions_json(w,"{\"x_test\":{\"version\":\"1\"}}"));
    {
        const int64_t shape[]={2};const unsigned char values[]={1,0,0,0,2,0,0,0};
        const qvf_opaque_input opaque={"log","plain text",10,"text/plain"};
        OK(qvf_writer_declare_section(w,"{\"id\":\"custom\",\"kind\":\"x_test.data\"}"));
        OK(qvf_writer_begin_binary(w,"custom","data",QVF_INT32,1,shape));OK(qvf_writer_write(w,values,4));OK(qvf_writer_abort_binary(w));
        OK(qvf_writer_begin_binary(w,"custom","data",QVF_INT32,1,shape));OK(qvf_writer_write(w,values,8));OK(qvf_writer_end_binary(w));
        OK(qvf_writer_add_opaque(w,"custom",&opaque));
    }
    OK(qvf_writer_bytes(w,&archive,&size));OK(qvf_reader_from_bytes(archive,size,NULL,&r));CHECK(check_valid(r));OK(qvf_reader_member_info(r,"custom","log",&info));CHECK(info.format==QVF_MEMBER_OPAQUE && info.nbytes==10);OK(qvf_reader_destroy(r));r=NULL;OK(qvf_writer_destroy(w));w=NULL;
    /* Legacy signatures stay repeatable and can adopt new canonical entries. */
    w=qvf_create("legacy","1","compat");CHECK(w);OK(add_periodic(w));OK(qvf_write(w,"c-api-edit.qvf"));OK(qvf_write(w,"c-api-edit.qvf"));qvf_destroy(w);w=NULL;
    OK(qvf_editor_open("c-api-edit.qvf",1,&e));OK(qvf_editor_writer(e,&w));
    CHECK(qvf_writer_finish(w)!=0);OK(qvf_writer_add_job_spec_json(w,"job","{\"job_type\":\"periodic\",\"structure_ref\":\"structure\"}"));
    OK(qvf_editor_commit(e));CHECK(qvf_writer_add_job_spec_json(w,"too_late","{\"job_type\":\"periodic\"}")!=0);OK(qvf_writer_destroy(w));w=NULL;OK(qvf_editor_destroy(e));e=NULL;
    OK(qvf_validate_path("c-api-edit.qvf",QVF_VALIDATE_ALL,NULL,1,&report));OK(qvf_report_ok(report,&ok));CHECK(ok);OK(qvf_report_destroy(report));report=NULL;
    /* Acquired handles own state even if the editor handle is destroyed. */
    OK(qvf_editor_open("c-api-edit.qvf",1,&e));OK(qvf_editor_writer(e,&w));OK(qvf_editor_destroy(e));e=NULL;OK(qvf_writer_add_job_spec_json(w,"abandoned","{\"job_type\":\"periodic\"}"));OK(qvf_writer_destroy(w));w=NULL;
    OK(qvf_reader_open("c-api-edit.qvf",NULL,&r));OK(qvf_reader_section_count(r,&n));CHECK(n==2);OK(qvf_reader_destroy(r));r=NULL;
    OK(qvf_repack("c-api-edit.qvf","c-api-repacked.qvf",0));
    OK(qvf_validate_path("missing-c-api-input.qvf",QVF_VALIDATE_ALL,NULL,1,&report));OK(qvf_report_ok(report,&ok));CHECK(!ok);OK(qvf_report_get(report,0,&finding));CHECK(strcmp(finding.code,"E_ZIP_UNREADABLE")==0);CHECK(strlen(finding.where)>0);OK(qvf_report_destroy(report));
    remove("c-api-edit.qvf");remove("c-api-repacked.qvf");puts("C ABI 1 checks passed");return 0;
}
