/* Inspect and validate an archive through the C ABI. License: Apache-2.0. */
#include "qvf/qvf_c.h"
#include <stdio.h>
int main(int argc,char** argv) {
    qvf_reader* r=NULL; qvf_report* report=NULL;
    size_t n=0,i;int ok=0,status=1;
    if(argc!=2){fprintf(stderr,"usage: %s archive.qvf\n",argv[0]);return 2;}
    if(qvf_reader_open(argv[1],NULL,&r) || qvf_reader_section_count(r,&n))goto done;
    printf("libqvf %s ABI %u, %zu sections\n",qvf_toolkit_version(),qvf_abi_version(),n);
    for(i=0;i<n;++i){const char *id,*kind;if(qvf_reader_section_id(r,i,&id)||qvf_reader_section_kind(r,i,&kind))goto done;printf("%s: %s\n",id,kind);}
    if(qvf_reader_validate(r,QVF_VALIDATE_ALL,1,&report)||qvf_report_ok(report,&ok)||qvf_report_count(report,&n))goto done;
    for(i=0;i<n;++i){qvf_finding f;if(qvf_report_get(report,i,&f))goto done;printf("%s %s: %s\n",f.code,f.where,f.message);}
    status=ok?0:1;
done:
    if(status)fprintf(stderr,"%s %s\n",qvf_global_error(),r?qvf_reader_last_error(r):"");
    qvf_report_destroy(report);qvf_reader_destroy(r);return status;
}
