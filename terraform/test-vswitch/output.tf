output "vm_name" {
  value = vsphere_virtual_machine.vm[*].name
}
