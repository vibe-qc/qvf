/* Read and rewrite every canonical kind using only the C ABI.
 * Usage: write_all_kinds_c input.qvf output.qvf
 * No JSON parser is needed; JSON fields/payloads remain library-owned text.
 * License: Apache-2.0. */
#include "qvf/qvf_c.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static char* copy_text(const char* text) {
    const size_t n = strlen(text)+1;
    char* p = (char*)malloc(n); if(p) memcpy(p,text,n); return p;
}
static int add_named(qvf_writer* w,const char* kind,const qvf_section_input* input) {
#define QVF_C_KIND(name, text) if(strcmp(kind,text)==0) return qvf_writer_add_##name(w,input);
#include "qvf/c_kinds_generated.h"
#undef QVF_C_KIND
    return qvf_writer_add_section(w,input); /* declared vendor namespaces */
}
int main(int argc,char** argv) {
    qvf_reader* r=NULL; qvf_writer* w=NULL;
    size_t ns=0,i,ntext; const char* text;
    int status=1;
    if(argc!=3) {fprintf(stderr,"usage: %s input.qvf output.qvf\n",argv[0]);return 2;}
    if(qvf_reader_open(argv[1],NULL,&r) || qvf_writer_create("c-kind-example","1","copy",argv[2],&w)) goto done;
    for(i=0;i<=QVF_ROOT_EXTENSIONS;++i) {
        if(qvf_reader_root_json(r,(qvf_root_block)i,&text,&ntext))goto done;
        if(strcmp(text,"null") && qvf_writer_set_root_json(w,(qvf_root_block)i,text))goto done;
    }
    if(qvf_reader_section_count(r,&ns))goto done;
    for(i=0;i<ns;++i) {
        const char *id,*kind; size_t nm=0,j; qvf_section_input input={0};
        qvf_json_input* jsons=NULL; qvf_binary_input* bins=NULL; qvf_opaque_input* opaque=NULL;
        int failed=1;
        if(qvf_reader_section_id(r,i,&id) || qvf_reader_section_kind(r,i,&kind) || qvf_reader_member_count(r,id,&nm))goto done;
        if(qvf_reader_section_fields_json(r,id,&text,&ntext))goto done;
        input.section_json=copy_text(text); if(!input.section_json)goto done;
        jsons=(qvf_json_input*)calloc(nm?nm:1,sizeof(*jsons));
        bins=(qvf_binary_input*)calloc(nm?nm:1,sizeof(*bins));
        opaque=(qvf_opaque_input*)calloc(nm?nm:1,sizeof(*opaque));
        if(!jsons || !bins || !opaque)goto section_done;
        input.json=jsons;input.binary=bins;input.opaque=opaque;
        for(j=0;j<nm;++j) {
            const char* role; qvf_member_info m; size_t need; void* bytes;
            if(qvf_reader_member_role(r,id,j,&role) || qvf_reader_member_info(r,id,role,&m))goto section_done;
            if(m.format==QVF_MEMBER_JSON) {
                if(qvf_reader_read_json(r,id,role,1,&text,&ntext))goto section_done;
                jsons[input.json_count].role=role;
                jsons[input.json_count].json=copy_text(text);
                if(!jsons[input.json_count].json)goto section_done;
                ++input.json_count; continue;
            }
            if(qvf_reader_read_binary(r,id,role,1,NULL,0,&need))goto section_done;
            bytes=malloc(need?need:1);if(!bytes)goto section_done;
            if(qvf_reader_read_binary(r,id,role,1,bytes,need,&need)){free(bytes);goto section_done;}
            if(m.format==QVF_MEMBER_BINARY) {
                qvf_tensor_view tensor={bytes,need,m.dtype,m.rank,m.shape,QVF_LITTLE_ENDIAN,QVF_DTYPE_UNKNOWN};
                bins[input.binary_count].role=role;bins[input.binary_count++].tensor=tensor;
            } else {
                opaque[input.opaque_count].role=role;opaque[input.opaque_count].data=bytes;
                opaque[input.opaque_count].size=need;opaque[input.opaque_count++].media_type=m.media_type;
            }
        }
        if(add_named(w,kind,&input))goto section_done;
        failed=0;
section_done:
        for(j=0;j<input.json_count;++j)free((void*)jsons[j].json);
        for(j=0;j<input.binary_count;++j)free((void*)bins[j].tensor.data);
        for(j=0;j<input.opaque_count;++j)free((void*)opaque[j].data);
        free(jsons);free(bins);free(opaque);free((void*)input.section_json);
        if(failed)goto done;
    }
    if(qvf_writer_finish(w))goto done;
    status=0;
done:
    if(status)fprintf(stderr,"C ABI: %s | %s | %s\n",qvf_global_error(),r?qvf_reader_last_error(r):"",w?qvf_last_error(w):"");
    qvf_writer_destroy(w);qvf_reader_destroy(r);return status;
}
