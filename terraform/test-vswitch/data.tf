
data "vsphere_datacenter" "pilotto" {
  name = "pilotto"
}

data "vsphere_datastore" "vsan" {
  name = "vsanDatastore"
  datacenter_id = data.vsphere_datacenter.pilotto.id
}

data "vsphere_network" "vlan10" {
  name = "VM Network"
  datacenter_id = data.vsphere_datacenter.pilotto.id
}

data "vsphere_virtual_machine" "tpl_ubuntu-base" {
  name = "ubuntu-base"
  datacenter_id = data.vsphere_datacenter.pilotto.id
}

data "vsphere_compute_cluster" "vsan" {
  datacenter_id = data.vsphere_datacenter.pilotto.id
  name = "vSAN"
}
