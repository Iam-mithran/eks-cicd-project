# AWS setup — do this once, before Step 7

Steps 1–6 need **no AWS account at all**. Everything from Step 7 onward does.
Work through this file once and the rest of the project just runs.

> ## 💸 Read this first — the cost
>
> An EKS cluster is **not free tier**. As of writing, the control plane alone is
> about **$0.10/hour (~$73/month)**, plus EC2 for the nodes and a little for ECR
> storage. Two `t3.small` nodes bring the total to roughly **$0.15–0.20/hour**.
>
> **For a learner: create the cluster, do Steps 7–14 in one or two sittings,
> then run the teardown in Part 7.** A weekend of practice costs a few dollars.
> A cluster you forgot about costs a few hundred. Set a billing alarm now:
> Billing → Budgets → create a $10 budget with an email alert.
>
> Prefer to spend nothing? Steps 1–6 and 10–12 all run without AWS. You still
> learn CI, containers, injection-safety and scanning — only the deploy needs
> a cluster.

## What you need installed

| Tool | Check | Install |
|---|---|---|
| AWS CLI v2 | `aws --version` | [docs](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |
| eksctl | `eksctl version` | [docs](https://eksctl.io/installation/) |
| kubectl | `kubectl version --client` | [docs](https://kubernetes.io/docs/tasks/tools/) |

Then `aws configure` with an IAM user that can create IAM roles, ECR
repositories and EKS clusters (admin, for a learning account).

Set these once in your shell — every command below uses them:

```bash
export AWS_REGION=ap-south-1                 # your region
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export GITHUB_ORG=your-github-username
export GITHUB_REPO=eks-cicd-project
export CLUSTER_NAME=taskapi-cluster
echo "Account: $AWS_ACCOUNT_ID  Region: $AWS_REGION"
```

---

## Part 1 — Create the ECR repository

This is where the pipeline pushes images.

```bash
aws ecr create-repository \
  --repository-name taskapi \
  --region "$AWS_REGION" \
  --image-scanning-configuration scanOnPush=true \
  --image-tag-mutability IMMUTABLE
```

Two flags worth understanding:

- **`scanOnPush=true`** — ECR scans every image for CVEs on arrival. A second
  opinion alongside the Trivy gate in Step 13, at no extra effort.
- **`IMMUTABLE`** — a tag, once pushed, can never be overwritten. This is what
  makes "the SHA tag identifies exactly these bytes" *true* rather than a
  convention people mean to follow. It also means re-running a build for the
  same commit fails on push; that is the feature working, not a bug.

Add a lifecycle policy so old images do not accumulate forever:

```bash
aws ecr put-lifecycle-policy \
  --repository-name taskapi \
  --region "$AWS_REGION" \
  --lifecycle-policy-text '{
    "rules": [{
      "rulePriority": 1,
      "description": "Keep the last 30 images",
      "selection": { "tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 30 },
      "action": { "type": "expire" }
    }]
  }'
```

---

## Part 2 — Tell AWS to trust GitHub (the OIDC provider)

This is the object that lets AWS verify a token GitHub signed. **One per AWS
account** — if you have ever set up OIDC for another repo, skip to Part 3.

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

Already exists? `EntityAlreadyExists` is fine — you are done with this part.

Verify:

```bash
aws iam list-open-id-connect-providers
```

---

## Part 3 — The IAM role the pipeline assumes

### 3a. The trust policy — *who* may assume the role

This is the security-critical file in the whole setup. Read the `sub`
condition carefully.

```bash
cat > trust-policy.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
      },
      "StringLike": {
        "token.actions.githubusercontent.com:sub": "repo:${GITHUB_ORG}/${GITHUB_REPO}:*"
      }
    }
  }]
}
JSON
```

> ### ⚠️ The mistake that hands your AWS account to the internet
>
> Plenty of blog posts show `"sub": "repo:*"` or omit the `sub` condition
> entirely. That trusts **every repository on GitHub**. Anyone can create a
> repo, run a workflow, and assume your role.
>
> The `sub` claim must always name **your** org and repo. Tighten it further
> once it works:
>
> | `sub` pattern | Who can assume the role |
> |---|---|
> | `repo:me/app:*` | any branch, any PR, any tag in that repo |
> | `repo:me/app:ref:refs/heads/main` | only workflows running on `main` |
> | `repo:me/app:environment:production` | only jobs targeting the `production` environment |
>
> The last one is the strongest: combined with a required reviewer, an AWS
> production credential cannot be minted at all until a human approves.

Create the role:

```bash
aws iam create-role \
  --role-name github-actions-taskapi \
  --assume-role-policy-document file://trust-policy.json \
  --description "Assumed by GitHub Actions for the taskapi pipeline"
```

### 3b. The permissions policy — *what* the role may do

```bash
cat > permissions-policy.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRAuth",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "ECRPushPull",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:CompleteLayerUpload",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
        "ecr:DescribeImages"
      ],
      "Resource": "arn:aws:ecr:*:*:repository/taskapi"
    },
    {
      "Sid": "DescribeTheCluster",
      "Effect": "Allow",
      "Action": "eks:DescribeCluster",
      "Resource": "*"
    }
  ]
}
JSON

aws iam put-role-policy \
  --role-name github-actions-taskapi \
  --policy-name taskapi-pipeline \
  --policy-document file://permissions-policy.json
```

Note how small that is. `ecr:GetAuthorizationToken` genuinely cannot be scoped
to a resource, but everything else is limited to the one repository, and the
only EKS permission is *describe* — enough to fetch a kubeconfig, and nothing
more. **Resist `AdministratorAccess`.** A pipeline is the one identity in your
account that runs code written by anyone who can open a pull request.

Save the ARN — you need it in a moment:

```bash
aws iam get-role --role-name github-actions-taskapi --query Role.Arn --output text
```

---

## Part 4 — The EKS cluster, and the permission everyone forgets

### 4a. Create the cluster

☕ **This takes 15–20 minutes.** It is not stuck.

```bash
eksctl create cluster \
  --name "$CLUSTER_NAME" \
  --region "$AWS_REGION" \
  --version 1.31 \
  --nodegroup-name workers \
  --node-type t3.small \
  --nodes 2 \
  --nodes-min 2 \
  --nodes-max 4 \
  --managed \
  --with-oidc
```

Check it:

```bash
kubectl get nodes
```

Two nodes in `Ready` state means the cluster is up **and** your local
kubeconfig works.

### 4b. 🔑 Let the pipeline's IAM role into the cluster

**This is the single most-missed step in the entire project.**

IAM controls the AWS API. Kubernetes has its own, completely separate
permission system. An IAM role that is an AWS administrator is, by default,
a *total stranger* to your cluster. Skip this and Step 8 fails with:

```
error: You must be logged in to the server (Unauthorized)
```

The fix — grant the role cluster-admin inside Kubernetes:

```bash
# 1. Register the IAM role as a cluster principal
aws eks create-access-entry \
  --cluster-name "$CLUSTER_NAME" \
  --region "$AWS_REGION" \
  --principal-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:role/github-actions-taskapi" \
  --type STANDARD

# 2. Say what it is allowed to do
aws eks associate-access-policy \
  --cluster-name "$CLUSTER_NAME" \
  --region "$AWS_REGION" \
  --principal-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:role/github-actions-taskapi" \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
  --access-scope type=cluster
```

Verify:

```bash
aws eks list-access-entries --cluster-name "$CLUSTER_NAME" --region "$AWS_REGION"
```

> **Cluster-admin is more than a deploy pipeline needs.** It is the right
> starting point while you are learning — one less thing failing at once. The
> production-grade version is `AmazonEKSEditPolicy` scoped to just the two
> namespaces:
>
> ```bash
> --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy \
> --access-scope type=namespace,namespaces=taskapi-staging,taskapi-prod
> ```
>
> Then a compromised pipeline cannot touch `kube-system`. Tighten this once
> Step 8 is green — changing two things at once is how you lose an evening.
>
> **On an older cluster** that predates access entries, the equivalent is
> editing the `aws-auth` ConfigMap:
> `eksctl create iamidentitymapping --cluster $CLUSTER_NAME --arn <role-arn> --group system:masters --username github-actions`

---

## Part 5 — Optional cluster add-ons

Skip both if you only want Steps 7–14 to pass. Steps 8, 9 and 14 verify the
deploy with `kubectl port-forward`, which needs neither.

**metrics-server** — required by `k8s/hpa.yaml`. Without it the HPA shows
`<unknown>/70%` forever:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl top nodes     # works after ~60s
```

**AWS Load Balancer Controller** — required by `k8s/ingress.yaml`. Without it
the Ingress object is created and silently ignored, and `ADDRESS` stays empty.
It also provisions a real ALB, which costs about **$16/month**. Follow the
[official install guide](https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html)
if you want a public URL.

---

## Part 6 — Wire it into GitHub

### 6a. Repository variables

**Settings → Secrets and variables → Actions → Variables tab → New variable**

| Name | Example value | Where it came from |
|---|---|---|
| `AWS_ROLE_ARN` | `arn:aws:iam::123456789012:role/github-actions-taskapi` | Part 3 |
| `AWS_REGION` | `ap-south-1` | your choice |
| `AWS_ACCOUNT_ID` | `123456789012` | `aws sts get-caller-identity` |
| `ECR_REPOSITORY` | `taskapi` | Part 1 |
| `EKS_CLUSTER_NAME` | `taskapi-cluster` | Part 4 |

**Why variables and not secrets?** None of these is a credential. An account
ID is not a password — the security boundary is the role's *trust policy*,
which is why Part 3 mattered so much. Secrets are masked as `***` in every
log, which turns a simple typo into an hour of blind debugging. Put
credentials in secrets; put configuration in variables.

Print them all in one go:

```bash
echo "AWS_ROLE_ARN     = arn:aws:iam::${AWS_ACCOUNT_ID}:role/github-actions-taskapi"
echo "AWS_REGION       = ${AWS_REGION}"
echo "AWS_ACCOUNT_ID   = ${AWS_ACCOUNT_ID}"
echo "ECR_REPOSITORY   = taskapi"
echo "EKS_CLUSTER_NAME = ${CLUSTER_NAME}"
```

### 6b. Environments (needed from Step 9)

**Settings → Environments → New environment**

- **`staging`** — no protection rules. Deploys run straight through.
- **`production`** — tick **Required reviewers** and add yourself. This is what
  pauses the run and shows the *Review deployments* button.

Optionally set **Deployment branches → Selected branches → `main`** on
`production`, so no branch other than `main` can ever deploy there.

### 6c. Security settings (needed from Step 12)

**Settings → Code security** — enable **Secret scanning**, **Push protection**,
**Dependabot alerts** and **Dependabot security updates**.

---

## Part 7 — 🧹 Tear it all down

**Do this the moment you finish.** The cluster bills by the hour whether you
use it or not.

```bash
# 1. Anything that created an AWS load balancer must go first, or the VPC
#    delete hangs and eksctl times out.
kubectl delete ingress --all -A --ignore-not-found
kubectl delete svc --all-namespaces --field-selector spec.type=LoadBalancer --ignore-not-found

# 2. The cluster and its nodes — the expensive part. ~10-15 minutes.
eksctl delete cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" --wait

# 3. The registry (cheap, but tidy)
aws ecr delete-repository --repository-name taskapi --region "$AWS_REGION" --force

# 4. The IAM role
aws iam delete-role-policy --role-name github-actions-taskapi --policy-name taskapi-pipeline
aws iam delete-role --role-name github-actions-taskapi
```

Leave the OIDC provider from Part 2 in place — it costs nothing and you will
want it for the next project.

**Then confirm you are actually at zero:** Billing → Cost Explorer, next
morning. A leftover NAT gateway or a stray EBS volume is the classic
surprise-bill culprit.

---

## 🔧 Troubleshooting

| Error in the log | What it actually means | Fix |
|---|---|---|
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | GitHub never sent an OIDC token | Add `permissions: id-token: write` to the job |
| Same error, token *was* sent | The trust policy `sub` does not match this repo/branch | Part 3a — check org, repo and branch spelling |
| `You must be logged in to the server (Unauthorized)` | AWS auth worked; **Kubernetes** does not know the role | Part 4b — the access entry |
| `denied: User is not authorized to perform ecr:PutImage` | Role lacks ECR push permission, or the repo name differs | Part 3b, and check `ECR_REPOSITORY` |
| `repository does not exist` on push | ECR repo missing in **this region** | Part 1 — regions are separate namespaces |
| `tag invalid: cannot overwrite immutable tag` | You re-ran a build for a commit already pushed | Expected: `IMMUTABLE` working. Push a new commit |
| Rollout hangs, pods `ImagePullBackOff` | Nodes cannot pull from ECR | Node role needs `AmazonEC2ContainerRegistryReadOnly` (eksctl attaches it by default) |
| Pods `CrashLoopBackOff` | The app itself is failing | `kubectl logs -n <ns> -l app=taskapi --tail=50` |
| Pods `Pending` forever | No node has room for the requested CPU/memory | `kubectl describe pod` → Events; scale the nodegroup |
| HPA shows `<unknown>/70%` | metrics-server not installed | Part 5 |
| Ingress `ADDRESS` stays empty | Load Balancer Controller not installed | Part 5 |

**The first command to run when a deploy fails**, before anything else:

```bash
kubectl get events -n taskapi-staging --sort-by=.lastTimestamp | tail -20
```

Kubernetes almost always already told you what is wrong. Steps 8 and 9 print
this for you automatically in their `if: failure()` step.
