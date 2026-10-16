! Synthetic layout example, not a scientific calculation. License: Apache-2.0.
program write_sections
  use qvf
  implicit none
  type(c_ptr) :: writer=c_null_ptr
  character(len=1024) :: path
  character(len=:), allocatable :: message
  real(c_double) :: positions(2,3), values(2,3,4), coords(2,2,3), cell(2,3,3), mo(2,2)
  integer :: i,j,k
  integer(c_int) :: status
  call get_command_argument(1,path)
  if (len_trim(path)==0) path='fortran_sections.qvf'
  call check(qvf_open(writer,trim(path),'fortran-example','1','synthetic layout',message))
  do i=1,2
    do j=1,3
      positions(i,j)=real(10*i+j,c_double)/10
      do k=1,2
        coords(k,i,j)=positions(i,j)+real(k-1,c_double)
      end do
    end do
  end do
  call check(qvf_structure(writer,[1_c_int,1_c_int],positions,message))
  do i=1,2
    do j=1,3
      do k=1,4
        values(i,j,k)=real(100*i+10*j+k,c_double)
      end do
    end do
  end do
  call check(qvf_volume(writer,'volume.generic', &
    '{"origin":[0,0,0],"voxel_vectors":[[1,0.1,0.2],[0.3,2,0.4],[0.5,0.6,3]]}',values,message))
  do i=1,2
    cell(i,:,:)=reshape([4.0_c_double,0.3_c_double,0.5_c_double, &
                         0.1_c_double,5.0_c_double,0.6_c_double, &
                         0.2_c_double,0.4_c_double,6.0_c_double],[3,3])*i
  end do
  call check(qvf_trajectory(writer,'{"symbols":["H","H"],"pbc":[true,false,true],"kind":"md"}', &
    coords,message,lattice=cell,velocities=coords/10,gradients=-coords/100, &
    times=[0.0_c_double,0.5_c_double],energies=[-1.0_c_double,-0.9_c_double]))
  mo=reshape([0.8_c_double,-0.6_c_double,0.6_c_double,0.8_c_double],[2,2])
  call check(qvf_gto(writer,[0_c_int,1_c_int],[0_c_int,0_c_int],[1_c_int,1_c_int], &
    [1.0_c_double,1.0_c_double],[1.0_c_double,1.0_c_double],mo,message, &
    energies=[-0.5_c_double,0.1_c_double],occupations=[2.0_c_double,0.0_c_double]))
  call check(qvf_finish(writer,message))
  status=qvf_close(writer)
  if (status/=QVF_OK .or. c_associated(writer)) error stop 'close failed'
contains
  subroutine check(code)
    integer(c_int), intent(in) :: code
    if (code/=QVF_OK) then
      print *,message
      status=qvf_close(writer)
      error stop 'QVF call failed'
    end if
  end subroutine
end program
