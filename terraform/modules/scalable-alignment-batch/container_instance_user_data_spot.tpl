MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="==MYBOUNDARY=="

--==MYBOUNDARY==
Content-Type: text/cloud-boothook; charset="us-ascii"

#!/bin/bash -ex

##############################################
# Mount drives
##############################################

yum install -y mdadm amazon-ssm-agent

aegea_bd=(/dev/disk/by-id/nvme-Amazon_EC2_NVMe_Instance_Storage_AWS?????????????????)
if [ ! -e /dev/md0 ]
then
    mdadm --create /dev/md0 --force --auto=yes --level=0 --chunk=256 --raid-devices=$${#aegea_bd[@]} $${aegea_bd[@]}
    mkfs.xfs /dev/md0
fi

mount /dev/md0 /mnt
mkdir /mnt/index_cache

##############################################
# Configure Docker to use NVME for scratch space
##############################################

cloud-init-per once docker_options echo "{\"data-root\": \"/mnt/docker\"}" >> /etc/docker/daemon.json

--==MYBOUNDARY==
Content-Type: text/x-shellscript; charset="us-ascii"

#!/bin/bash -ex

##############################################
# Configure logging and monitoring
##############################################

# Install the cloudwatch agent
curl -O https://s3.us-west-2.amazonaws.com/amazoncloudwatch-agent-us-west-2/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
rpm -U ./amazon-cloudwatch-agent.rpm

# Configure the cloudwatch agent
LOG_CONFIG=/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json
mkdir -p $(dirname $LOG_CONFIG)
echo "${log_configuration}" >> $LOG_CONFIG

# Start the cloudwatch agent
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:$LOG_CONFIG -s


##############################################
# Configure instance
##############################################

# Tweak VM params to speed up download
sysctl vm.dirty_expire_centisecs=30000
sysctl vm.dirty_background_ratio=5
sysctl vm.dirty_ratio=60

# Prevent hour-long system stalls due to Virtual Memory defragmenting
bash -c "echo never > /sys/kernel/mm/transparent_hugepage/defrag"

--==MYBOUNDARY==--