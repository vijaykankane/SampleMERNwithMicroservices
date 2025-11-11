import boto3
import base64
from botocore.exceptions import ClientError

# -------------------- CONFIG --------------------
PROJECT_NAME = "vijay-new-43-backend-project"
REGION = "eu-central-1"
AMI_ID = "ami-04e601abe3e1a910f"  # Amazon Linux 2 (adjust for your region)
INSTANCE_TYPE = "t2.micro"
KEY_NAME = f"{PROJECT_NAME}-key"
PEM_PATH = f"C:/Users/Pranvi Kankane/OneDrive/Desktop/VLearn-boto-3-project/{KEY_NAME}.pem"
MIN_SIZE = 1
MAX_SIZE = 2
DESIRED_CAPACITY = 1
# -------------------------------------------------

ec2 = boto3.resource('ec2', region_name=REGION)
ec2_client = boto3.client('ec2', region_name=REGION)
asg = boto3.client('autoscaling', region_name=REGION)
elbv2 = boto3.client('elbv2', region_name=REGION)

# -------------------- FUNCTIONS --------------------

def create_vpc():
    print("Creating VPC...")
    vpcs = list(ec2.vpcs.all())
    if len(vpcs) >= 4:
        print("⚠️ You have reached VPC limit. Using existing VPC:", vpcs[0].id)
        return vpcs[0].id
    vpc = ec2.create_vpc(CidrBlock='10.102.0.0/16')
    vpc.wait_until_available()
    vpc.create_tags(Tags=[{'Key': 'Name', 'Value': PROJECT_NAME}])
    print(f"VPC created: {vpc.id}")
    return vpc.id

def create_internet_gateway(vpc_id):
    print("Attaching Internet Gateway...")
    igw = ec2.create_internet_gateway()
    igw.attach_to_vpc(VpcId=vpc_id)
    print(f"Attached Internet Gateway {igw.id}")
    return igw.id

def create_subnets(vpc_id):
    print("Creating 2 public subnets...")
    subnet1 = ec2.create_subnet(VpcId=vpc_id, CidrBlock='10.102.1.0/24', AvailabilityZone=f'{REGION}a')
    subnet2 = ec2.create_subnet(VpcId=vpc_id, CidrBlock='10.102.2.0/24', AvailabilityZone=f'{REGION}b')
    print(f"Subnets created: {subnet1.id}, {subnet2.id}")
    return [subnet1.id, subnet2.id]

def create_route_table(vpc_id, igw_id):
    print("Creating route table...")
    route_table = ec2.create_route_table(VpcId=vpc_id)
    route_table.create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=igw_id)
    print(f"Created Route Table {route_table.id}")
    return route_table.id

def create_security_group(vpc_id):
    print("Creating Security Group (HTTP, SSH)...")
    sg = ec2.create_security_group(
        GroupName=f"{PROJECT_NAME}-sg",
        Description="Allow HTTP and SSH",
        VpcId=vpc_id
    )
    sg.authorize_ingress(IpPermissions=[
        {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22,
         'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
        {'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80,
         'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
    ])
    print(f"Security Group created: {sg.id}")
    return sg.id

def create_key_pair():
    print("Creating Key Pair...")
    try:
        keypair = ec2_client.create_key_pair(KeyName=KEY_NAME)
        with open(PEM_PATH, 'w') as f:
            f.write(keypair['KeyMaterial'])
        print(f"Key saved: {PEM_PATH}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidKeyPair.Duplicate':
            print("✅ Key Pair already exists, skipping creation.")
        else:
            raise

def create_launch_template(sg_id):
    print("Creating Launch Template...")
    user_data_script = """#!/bin/bash
    sudo apt update -y
sudo apt install -y nginx
sudo systemctl enable nginx
sudo systemctl start nginx
echo '<h1>Hello from Boto3 EC2 via ASG!</h1>' > /var/www/html/index.html
    """
    encoded_script = base64.b64encode(user_data_script.encode("utf-8")).decode("utf-8")

    try:
        lt = ec2_client.create_launch_template(
            LaunchTemplateName=f"{PROJECT_NAME}-lt",
            LaunchTemplateData={
                'ImageId': AMI_ID,
                'InstanceType': INSTANCE_TYPE,
                'KeyName': KEY_NAME,
                'SecurityGroupIds': [sg_id],
                'UserData': encoded_script
            }
        )
        lt_id = lt['LaunchTemplate']['LaunchTemplateId']
        print(f"Created Launch Template {lt_id}")
        return lt_id
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidLaunchTemplateName.AlreadyExistsException':
            existing = ec2_client.describe_launch_templates(
                LaunchTemplateNames=[f"{PROJECT_NAME}-lt"]
            )['LaunchTemplates'][0]['LaunchTemplateId']
            print(f"✅ Using existing Launch Template {existing}")
            return existing
        else:
            raise

def create_asg(lt_id, subnet_ids, target_group_arn=None):
    print("Creating Auto Scaling Group...")
    asg.create_auto_scaling_group(
        AutoScalingGroupName=f"{PROJECT_NAME}-asg",
        LaunchTemplate={'LaunchTemplateId': lt_id},
        MinSize=MIN_SIZE,
        MaxSize=MAX_SIZE,
        DesiredCapacity=DESIRED_CAPACITY,
        VPCZoneIdentifier=",".join(subnet_ids),
        TargetGroupARNs=[target_group_arn] if target_group_arn else [],
        Tags=[{'Key': 'Name', 'Value': f"{PROJECT_NAME}-ec2"}]
    )
    print(f"ASG created: {PROJECT_NAME}-asg")

def create_load_balancer(subnet_ids, sg_id):
    print("Creating Application Load Balancer (ALB)...")
    alb = elbv2.create_load_balancer(
        Name=f"{PROJECT_NAME}-alb",
        Subnets=subnet_ids,
        SecurityGroups=[sg_id],
        Scheme='internet-facing',
        Type='application',
        IpAddressType='ipv4'
    )
    alb_arn = alb['LoadBalancers'][0]['LoadBalancerArn']
    print(f"ALB created: {alb_arn}")
    return alb_arn

def create_target_group(vpc_id):
    print("Creating Target Group...")
    tg = elbv2.create_target_group(
        Name=f"{PROJECT_NAME}-tg",
        Protocol='HTTP',
        Port=80,
        VpcId=vpc_id,
        TargetType='instance'
    )
    tg_arn = tg['TargetGroups'][0]['TargetGroupArn']
    print(f"Target Group created: {tg_arn}")
    return tg_arn

def create_listener(alb_arn, tg_arn):
    print("Creating Listener...")
    listener = elbv2.create_listener(
        LoadBalancerArn=alb_arn,
        Protocol='HTTP',
        Port=80,
        DefaultActions=[{'Type': 'forward', 'TargetGroupArn': tg_arn}]
    )
    print(f"Listener created: {listener['Listeners'][0]['ListenerArn']}")
    return listener['Listeners'][0]['ListenerArn']

# -------------------- MAIN --------------------
def main():
    vpc_id = create_vpc()
    igw_id = create_internet_gateway(vpc_id)
    subnet_ids = create_subnets(vpc_id)
    create_route_table(vpc_id, igw_id)
    sg_id = create_security_group(vpc_id)
    create_key_pair()
    lt_id = create_launch_template(sg_id)
    alb_arn = create_load_balancer(subnet_ids, sg_id)
    tg_arn = create_target_group(vpc_id)
    create_listener(alb_arn, tg_arn)
    create_asg(lt_id, subnet_ids, tg_arn)
    print("\n✅ Infrastructure successfully created!")
    print(f"VPC: {vpc_id}")
    print(f"Subnets: {subnet_ids}")
    print(f"SG: {sg_id}")
    print(f"ASG: {PROJECT_NAME}-asg")
    print(f"ALB: {alb_arn}")

if __name__ == "__main__":
    main()
