provider "vsphere" {
  user = var.vsphere_user
  password = var.vsphere_password
  vsphere_server = var.vsphere_server
  allow_unverified_ssl = true
}

variable "vm_counts" { default = 3 }


resource "random_pet" "name" {
  length = 1
  count = var.vm_counts
}

resource "vsphere_virtual_machine" "vm" {

  count = var.vm_counts

  name = random_pet.name[count.index].id
  folder = "test-ovs"

  memory = 4096
  num_cpus = 4

  resource_pool_id = data.vsphere_compute_cluster.vsan.resource_pool_id

  clone {
    template_uuid = data.vsphere_virtual_machine.tpl_ubuntu-base.id
    linked_clone = false

    customize {
      network_interface {}  # DHCP

      linux_options {
        domain = "dc-pilotto.my-ideas.it"
        host_name = random_pet.name[count.index].id
        hw_clock_utc = true
        time_zone = "Europe/Rome"
      }
    }
  }

  guest_id = data.vsphere_virtual_machine.tpl_ubuntu-base.guest_id
  scsi_type = data.vsphere_virtual_machine.tpl_ubuntu-base.scsi_type

  disk {
    label = "disk0"
    size = data.vsphere_virtual_machine.tpl_ubuntu-base.disks.0.size
  }

  network_interface {
    network_id = data.vsphere_network.vlan10.id
  }

}
