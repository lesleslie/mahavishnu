# AI Governance & Ethics Guide

**Comprehensive guide to responsible AI development, deployment, and monitoring with Mahavishnu Orchestrator.**

---

## Table of Contents

1. [Introduction](#introduction)
2. [AI Ethics Principles](#ai-ethics-principles)
3. [Bias Detection & Mitigation](#bias-detection--mitigation)
4. [Explainability & Transparency](#explainability--transparency)
5. [Privacy & Data Protection](#privacy--data-protection)
6. [AI Safety Monitoring](#ai-safety-monitoring)
7. [Regulatory Compliance](#regulatory-compliance)
8. [Pre-Deployment Checklist](#pre-deployment-checklist)
9. [Training Materials](#training-materials)
10. [Case Studies](#case-studies)
11. [Best Practices](#best-practices)
12. [Troubleshooting](#troubleshooting)

---

## Introduction

### What is AI Governance?

AI Governance is the framework of policies, practices, and processes that ensure artificial intelligence systems are developed and deployed responsibly, ethically, and in compliance with regulations. It encompasses:

- **Ethical AI**: Ensuring AI systems align with human values and do not cause harm
- **Fairness**: Preventing discriminatory outcomes and bias
- **Transparency**: Making AI decisions understandable and explainable
- **Accountability**: Establishing clear responsibility for AI outcomes
- **Privacy**: Protecting personal data and respecting user rights
- **Safety**: Ensuring AI systems operate reliably and securely
- **Compliance**: Meeting legal and regulatory requirements

### Why AI Governance Matters

**Business Risks of Poor AI Governance:**

- **Legal Liability**: Discrimination lawsuits, GDPR fines (up to €20M or 4% of revenue)
- **Reputation Damage**: Loss of customer trust, brand damage
- **Financial Loss**: Costly recalls, remediation expenses, regulatory penalties
- **Operational Disruption**: System failures, biased decisions requiring manual intervention
- **Regulatory Blocking**: Inability to deploy in regulated markets

**Benefits of Strong AI Governance:**

- **Competitive Advantage**: Trust is a differentiator in AI products
- **Regulatory Readiness**: Prepared for evolving AI regulations
- **Better Products**: Fair, accurate, reliable AI systems
- **Risk Reduction**: Fewer incidents, lawsuits, and recalls
- **Market Access**: Ability to deploy in regulated industries (finance, healthcare, EU)
- **Customer Trust**: Transparent, ethical AI builds user confidence

### Mahavishnu AI Governance Framework

Mahavishnu provides a comprehensive CLI toolkit for AI governance:

```
mahavishnu ethics <domain> <action>
```

**Domains:**

- `bias` - Bias detection and mitigation
- `explain` - Explainability and transparency
- `privacy` - Data protection and privacy
- `safety` - AI safety monitoring
- `compliance` - Regulatory compliance

**Quick Start Example:**

```bash
# Detect bias in a credit scoring model
mahavishnu ethics bias detect \
    --model ./models/credit_scoring.pkl \
    --dataset ./data/applications.csv \
    --attribute gender \
    --attribute race \
    --threshold 0.8

# Generate comprehensive audit report
mahavishnu ethics compliance audit \
    --model ./models/loan_approval.pkl \
    --type full \
    --output ./audit_report.json
```

---

## AI Ethics Principles

### Core Principles for Responsible AI

#### 1. Fairness and Non-Discrimination

**Definition:** AI systems should not produce discriminatory outcomes against individuals or groups based on protected characteristics (race, gender, age, religion, disability, etc.).

**Implementation:**

```python
# Example: Fairness-aware model training
from fairlearn.reductions import ExponentiatedGradient
from fairlearn.metrics import demographic_parity_difference

# Train model with fairness constraint
mitigator = ExponentiatedGradient(
    estimator=model,
    constraints=DemographicParity()
)
mitigator.fit(X_train, y_train, sensitive_features=train_df['gender'])

# Evaluate fairness
dp_diff = demographic_parity_difference(
    y_true, y_pred, sensitive_features=test_df['gender']
)
print(f"Demographic Parity Difference: {dp_diff:.3f}")
# Target: < 0.05 (below legal threshold)
```

**Key Metrics:**

- **Demographic Parity**: Equal prediction rates across groups
- **Equal Opportunity**: Equal true positive rates across groups
- **Disparate Impact**: Ratio of positive outcomes (target: > 0.8)
- **Calibration**: Equal prediction accuracy across groups

#### 2. Transparency and Explainability

**Definition:** AI decisions should be understandable and explainable to affected parties, regulators, and developers.

**Implementation:**

```python
# Example: SHAP explanations for individual predictions
import shap

# Create explainer
explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X_test)

# Explain single prediction
shap.force_plot(
    explainer.expected_value,
    shap_values[0,:],
    X_test.iloc[0,:],
    feature_names=feature_names
)

# Generate global explanation
shap.summary_plot(shap_values, X_test, feature_names=feature_names)
```

**Transparency Requirements:**

- **Local Explainability**: Explain individual predictions
- **Global Explainability**: Understand overall model behavior
- **Feature Importance**: Identify influential factors
- **Decision Boundaries**: Understand when/why decisions change

#### 3. Privacy and Data Minimization

**Definition:** AI systems should collect and use only necessary data, protect personal information, and respect user privacy rights.

**Implementation:**

```python
# Example: Differential privacy for training
from opendp.mod import Domain, Measurement
import opendp.prelude as dp

# Create private mean estimator
context = dp.Context.compositor(
    data=dp.vector_domain(dp.atom_domain(T=float)),
    privacy_unit=dp.unit_of(dp.contributions_max=1),
    privacy_loss=dp.loss_of(dp.epsilon=1.0, delta=1e-6)
)

# Compute private statistics
private_mean = (
    context.query()
    .laplace()
    .mean()
    .release()
)
print(f"Private mean: {private_mean}")
```

**Privacy Techniques:**

- **Differential Privacy**: Mathematical privacy guarantee
- **K-Anonymity**: Group indistinguishability (k ≥ 5)
- **Data Minimization**: Collect only necessary data
- **Purpose Limitation**: Use data only for stated purposes
- **Consent Management**: Track and respect user consent

#### 4. Accountability and Oversight

**Definition:** Clear lines of responsibility, auditability, and human oversight for AI systems.

**Implementation:**

```python
# Example: Model decision logging
import json
from datetime import datetime

def log_prediction(model_id, input_data, prediction, explanation):
    """Log all model decisions for audit trail."""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "model_id": model_id,
        "input_hash": hashlib.sha256(str(input_data).encode()).hexdigest(),
        "prediction": prediction,
        "explanation": explanation,
        "user_id": input_data.get("user_id"),
        "confidence": prediction.get("confidence"),
        "human_reviewed": False
    }

    with open("model_decisions.logl", "a") as f:
        f.write(json.dumps(log_entry) + "\n")

# Human-in-the-loop review
def requires_human_review(prediction):
    """Determine if prediction needs human review."""
    return (
        prediction["confidence"] < 0.8 or
        prediction.get("risk_level") == "high" or
        prediction.get("protected_class_impact") > 0.1
    )
```

**Accountability Mechanisms:**

- **Audit Trails**: Log all AI decisions
- **Human-in-the-Loop**: Human review for high-stakes decisions
- **Model Versioning**: Track which model made which decision
- **Appeals Process**: Mechanism to challenge AI decisions
- **Clear Ownership**: Defined responsibility for model outcomes

#### 5. Safety and Reliability

**Definition:** AI systems should operate safely, reliably, and within defined parameters without causing harm.

**Implementation:**

```python
# Example: Input validation and safety checks
def safe_predict(model, input_data):
    """Validate input and ensure safe prediction."""

    # Input validation
    if not validate_input(input_data):
        raise ValueError("Invalid input format")

    # Safety checks
    if input_data.get("amount", 0) > 1_000_000:
        # Flag for manual review
        return {
            "prediction": "REVIEW_REQUIRED",
            "reason": "Amount exceeds automatic approval threshold",
            "confidence": 0.0
        }

    # Get prediction
    prediction = model.predict(input_data)

    # Output validation
    if not validate_output(prediction):
        raise ValueError("Invalid prediction format")

    # Safety bounds
    prediction["confidence"] = min(max(prediction["confidence"], 0), 1)

    return prediction
```

**Safety Practices:**

- **Input Validation**: Reject malformed or adversarial inputs
- **Output Validation**: Ensure predictions are reasonable
- **Fail-Safe Defaults**: Safe fallback on errors
- **Monitoring**: Real-time safety metric tracking
- **Testing**: Adversarial and edge case testing

---

## Bias Detection & Mitigation

### Understanding AI Bias

**Types of Bias:**

| Bias Type | Description | Example |
|-----------|-------------|---------|
| **Selection Bias** | Non-representative training data | Training only on approved loans |
| **Measurement Bias** | Flawed feature measurement | Using proxy variables (zip code) |
| **Algorithmic Bias** | Biased model design | Objective function optimizing for majority |
| **Execution Bias** | Biased deployment context | Model used in different population |
| **Label Bias** | Biased ground truth labels | Human annotators' subjective labels |

### Bias Detection Workflow

#### Step 1: Define Protected Attributes

```python
protected_attributes = {
    "gender": ["male", "female", "non_binary"],
    "race": ["white", "black", "asian", "hispanic", "other"],
    "age": ["<25", "25-40", "40-60", ">60"],
    "disability": ["yes", "no"]
}
```

#### Step 2: Run Bias Detection

```bash
mahavishnu ethics bias detect \
    --model ./models/hiring.pkl \
    --dataset ./data/applicants.csv \
    --attribute gender \
    --attribute race \
    --attribute age \
    --threshold 0.8 \
    --output ./bias_report.json
```

#### Step 3: Analyze Results

```python
import json

with open("bias_report.json") as f:
    report = json.load(f)

for metric in report["metrics"]:
    attr = metric["attribute"]
    fairness = metric["overall_fairness"]
    risk = metric["risk_level"]

    if risk in ["high", "critical"]:
        print(f"⚠️ {attr}: {fairness:.2f} ({risk.upper()})")
    else:
        print(f"✓ {attr}: {fairness:.2f}")
```

#### Step 4: Mitigate Bias

```bash
mahavishnu ethics bias mitigate \
    --model ./models/hiring.pkl \
    --dataset ./data/applicants.csv \
    --technique adversarial \
    --target 0.90 \
    --output ./models/hiring_fair.pkl
```

### Bias Mitigation Techniques

#### 1. Preprocessing Techniques

**Reweighting:**

```python
from fairlearn.reweights import reweight

# Adjust sample weights to balance representation
sample_weights = reweight(
    y_train,
    sensitive_features=train_df['gender']
)

model.fit(X_train, y_train, sample_weight=sample_weights)
```

**Resampling:**

```python
from imblearn.over_sampling import SMOTE

# Oversample underrepresented groups
smote = SMOTE(sampling_strategy='minority')
X_balanced, y_balanced = smote.fit_resample(X_train, y_train)
```

#### 2. In-Processing Techniques

**Adversarial Debiasing:**

```python
from fairlearn.reductions import ExponentiatedGradient
from fairlearn.constraints import EqualizedOdds

# Train model to be fair while maximizing accuracy
mitigator = ExponentiatedGradient(
    estimator=base_model,
    constraints=EqualizedOdds()
)

mitigator.fit(
    X_train, y_train,
    sensitive_features=train_df['gender']
)
```

**Fairness-Constrained Optimization:**

```python
# Add fairness penalty to loss function
def fair_loss(y_true, y_pred, sensitive_attr):
    prediction_diff = demographic_parity_difference(
        y_true, y_pred, sensitive_features=sensitive_attr
    )

    # Standard loss + fairness penalty
    return (
        binary_crossentropy(y_true, y_pred) +
        lambda_fairness * prediction_diff
    )
```

#### 3. Post-Processing Techniques

**Threshold Adjustment:**

```python
# Group-specific thresholds to equalize outcomes
thresholds = {
    "male": 0.65,
    "female": 0.55,  # Lower threshold to equalize approval
    "non_binary": 0.55
}

def fair_predict_proba(proba, group):
    threshold = thresholds[group]
    return (proba >= threshold).astype(int)
```

**Calibration:**

```python
from sklearn.calibration import CalibratedClassifierCV

# Ensure prediction confidence is accurate across groups
calibrated_model = CalibratedClassifierCV(
    base_model,
    method='isotonic',
    cv='prefit'
)
calibrated_model.fit(X_cal, y_cal)
```

### Measuring Fairness

**Key Metrics:**

```python
from fairlearn.metrics import (
    demographic_parity_difference,
    equalized_odds_difference,
    selection_rate,
    false_negative_rate
)

# Demographic Parity
dp_diff = demographic_parity_difference(
    y_true, y_pred,
    sensitive_features=test_df['gender']
)
print(f"Demographic Parity Diff: {dp_diff:.3f}")
# Target: < 0.05

# Equalized Odds
eo_diff = equalized_odds_difference(
    y_true, y_pred,
    sensitive_features=test_df['race']
)
print(f"Equalized Odds Diff: {eo_diff:.3f}")
# Target: < 0.05

# Disparate Impact Ratio
selection_rate_a = selection_rate(y_pred[sensitive_attr == 'A'])
selection_rate_b = selection_rate(y_pred[sensitive_attr == 'B'])
disparate_impact = selection_rate_b / selection_rate_a
print(f"Disparate Impact: {disparate_impact:.3f}")
# Target: > 0.8 (80% rule)
```

### Continuous Bias Monitoring

```bash
# Set up continuous monitoring
mahavishnu ethics bias detect \
    --model ./models/production.pkl \
    --dataset ./data/weekly_sample.csv \
    --schedule weekly \
    --alert-threshold 0.75 \
    --webhook https://hooks.slack.com/...
```

---

## Explainability & Transparency

### Why Explainability Matters

**Legal Requirements:**

- **GDPR Article 22**: Right to explanation for automated decisions
- **EU AI Act**: Transparency requirements for high-risk AI
- **NYC Local Law 144**: Bias audits require explanation methods

**Business Benefits:**

- **Debugging**: Understand why models make mistakes
- **Trust**: Users more likely to adopt explainable AI
- **Regulatory Approval**: Required for regulated industries
- **Feature Engineering**: Identify important features

### Explainability Methods

#### 1. SHAP (SHapley Additive exPlanations)

**Best for:** Any model type, local and global explanations

```python
import shap

# Tree-based models (fast, exact)
explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X_test)

# Deep learning models
explainer = shap.DeepExplainer(model, X_train)
shap_values = explainer.shap_values(X_test)

# Any model (model-agnostic)
explainer = shap.KernelExplainer(model.predict_proba, X_train)
shap_values = explainer.shap_values(X_test)

# Local explanation for single prediction
shap.force_plot(
    explainer.expected_value,
    shap_values[0,:],
    X_test.iloc[0,:],
    feature_names=feature_names,
    matplotlib=True
)

# Global feature importance
shap.summary_plot(shap_values, X_test, feature_names=feature_names)

# Dependence plots (feature interactions)
shap.dependence_plot("age", shap_values, X_test)
```

#### 2. LIME (Local Interpretable Model-agnostic Explanations)

**Best for:** Local explanations, any model type

```python
import lime
import lime.lime_tabular

# Create explainer
explainer = lime.lime_tabular.LimeTabularExplainer(
    X_train.values,
    feature_names=feature_names,
    class_names=['deny', 'approve'],
    mode='classification'
)

# Explain single prediction
exp = explainer.explain_instance(
    X_test.iloc[0],
    model.predict_proba,
    num_features=10
)

# Visualize
exp.show_in_notebook(show_table=True)

# Get as list
exp.as_list()
```

#### 3. Feature Importance (Global)

**Best for:** Understanding overall model behavior

```python
import matplotlib.pyplot as plt

# Tree-based models
importances = model.feature_importances_
indices = np.argsort(importances)[::-1]

plt.figure(figsize=(12, 6))
plt.title("Feature Importances")
plt.bar(range(X_train.shape[1]), importances[indices])
plt.xticks(range(X_train.shape[1]), [feature_names[i] for i in indices], rotation=90)
plt.tight_layout()
plt.savefig('feature_importance.png')

# Permutation importance (model-agnostic)
from sklearn.inspection import permutation_importance

result = permutation_importance(
    model, X_test, y_test,
    n_repeats=10, random_state=42
)

sorted_idx = result.importances_mean.argsort()[::-1]
plt.bar(range(X_test.shape[1]), result.importances_mean[sorted_idx])
plt.xticks(range(X_test.shape[1]), [feature_names[i] for i in sorted_idx], rotation=90)
```

#### 4. Counterfactual Explanations

**Best for:** User-friendly explanations ("what if" scenarios)

```python
from alibi.explainers import CounterfactualExplainer

# Generate counterfactual
explainer = CounterfactualExplainer(
    model.predict,
    shape=X_test.shape[1:]
)

# Find what changes would flip the decision
cf = explainer.explain(
    X_test.iloc[0].values,
    target_class=1  # Desired outcome
)

print("To get approved, change:")
for feature, original, new in cf['changes']:
    print(f"  {feature}: {original} → {new}")
```

**Example Output:**

```
Current Prediction: DENIED (confidence: 0.34)

To get APPROVED, change:
  • income: $45,000 → $52,000
  • debt_to_income: 0.45 → 0.35
  • credit_score: 620 → 660

Feasibility: MEDIUM (2 changes required)
```

### Explainability CLI Commands

```bash
# Explain individual decision
mahavishnu ethics explain decision \
    --model ./models/credit.pkl \
    --input '{"income": 45000, "debt": 15000, "credit_score": 620}' \
    --method shap \
    --top 10 \
    --visualize

# Generate global explanation
mahavishnu ethics explain global \
    --model ./models/fraud_detection.pkl \
    --dataset ./data/transactions.csv \
    --method feature_importance \
    --output ./explanations/global.json

# Counterfactual explanation
mahavishnu ethics explain counterfactual \
    --model ./models/loan.pkl \
    --input '{"income": 45000, "credit_score": 620}' \
    --target approve \
    --num 5
```

### Trade-offs: Accuracy vs. Interpretability

```
High Interpretability ────────┬─────── Low Interpretability
                              │
Decision Trees                │    Neural Networks
Linear/Logistic Regression    │    Gradient Boosting
Rule-Based Systems            │    Ensemble Methods
                              │
    Low Accuracy ──────────────┼─────── High Accuracy
```

**Best Practice:** Start with interpretable models (linear, decision trees). Only use complex models if accuracy gain justifies interpretability loss.

---

## Privacy & Data Protection

### Privacy Frameworks

**GDPR (EU):**

- Legal basis for data processing
- Data minimization
- Purpose limitation
- Right to explanation (AI decisions)
- Right to erasure
- Data portability
- Privacy by design and by default

**CCPA (California):**

- Right to know what data is collected
- Right to delete data
- Right to opt-out of data sale
- Right to non-discrimination

**HIPAA (Healthcare):**

- Protected health information (PHI)
- Minimum necessary standard
- Business associate agreements
- Breach notification

### Privacy-Preserving Techniques

#### 1. Differential Privacy

**Guarantee:** Mathematical guarantee that individual records cannot be distinguished in aggregated data.

```python
# Example: Private mean with OpenDP
import opendp.prelude as dp

# Enable OpenDP
dp.enable_features("floating-point", "contrib")

# Create private mean with ε=1.0, δ=1e-6
context = (
    dp.Context.compositor(
        data=dp.vector_domain(dp.atom_domain(T=float)),
        privacy_unit=dp.unit_of(dp.contributions_max=1),
        privacy_loss=dp.loss_of(dp.epsilon=1.0, delta=1e-6)
    )
)

private_mean = (
    context.query()
    .laplace()
    .mean()
    .release()
)

print(f"Private mean: {private_mean}")
# Any individual's data has negligible impact (< 1e-6) on result
```

**Choosing ε (Privacy Budget):**

| ε Value | Privacy | Utility | Use Case |
|---------|---------|---------|----------|
| 0.1 | Very strong | Low | Highly sensitive data (medical) |
| 1.0 | Strong | Medium | General purpose (default) |
| 10.0 | Moderate | High | Public datasets |
| ∞ | None | Perfect | No privacy protection |

#### 2. K-Anonymity

**Guarantee:** Each record is indistinguishable from at least k-1 other records.

```python
from sympy.cluster.util import defaultdict

def check_k_anonymity(df, quasi_identifiers, k=5):
    """Check if dataset satisfies k-anonymity."""

    # Group by quasi-identifiers
    grouped = df.groupby(quasi_identifiers).size()

    # Check all groups have size ≥ k
    violations = grouped[grouped < k]

    if len(violations) > 0:
        print(f"K-anonymity violated: {len(violations)} groups < {k}")
        return False
    else:
        print(f"Dataset satisfies {k}-anonymity")
        return True

# Example
check_k_anonymity(
    df=patients,
    quasi_identifiers=['zip_code', 'age', 'gender'],
    k=5
)
```

**Achieving K-Anonymity:**

```python
# Generalization
df['age_group'] = pd.cut(
    df['age'],
    bins=[0, 25, 40, 60, 100],
    labels=['<25', '25-40', '40-60', '>60']
)

# Suppression
df = df[df['age_group'].map(df['age_group'].value_counts()) >= 5]
```

#### 3. Pseudonymization

**Goal:** Replace direct identifiers with pseudonyms while maintaining data utility.

```python
import hashlib
import uuid

def pseudonymize_pii(df, pii_columns):
    """Replace PII with pseudonyms."""

    # Create mapping table
    mapping = {}

    for col in pii_columns:
        df[f'{col}_pseudo'] = df[col].apply(lambda x: (
            hashlib.sha256(str(x).encode()).hexdigest()[:16]
            if x not in mapping else mapping[x]
        ))

    # Drop original PII
    df = df.drop(columns=pii_columns)

    return df, mapping

# Usage
df_anon, mapping = pseudonymize_pii(
    df=customers,
    pii_columns=['name', 'email', 'phone', 'ssn']
)

# Save mapping securely (encrypt, access control)
```

#### 4. Federated Learning

**Goal:** Train models without centralizing sensitive data.

```python
import tensorflow as tf
import tensorflow_federated as tff

# Define model function
def model_fn():
    model = tf.keras.Sequential([
        tf.keras.layers.Dense(10, activation='relu'),
        tf.keras.layers.Dense(1, activation='sigmoid')
    ])

    return tff.learning.from_keras_model(
        model,
        input_spec=...,  # Client data spec
        loss=tf.keras.losses.BinaryCrossentropy(),
        metrics=[tf.keras.metrics.AUC()]
    )

# Create federated learning process
trainer = tff.learning.build_federated_averaging_process(
    model_fn,
    client_optimizer_fn=lambda: tf.keras.optimizers.SGD(0.1),
    server_optimizer_fn=lambda: tf.keras.optimizers.SGD(1.0)
)

# Train on distributed data (data never leaves client devices)
state = trainer.initialize()
for round_num in range(100):
    state, metrics = trainer.next(state, federated_train_data)
```

### Privacy Impact Assessment (PIA)

**When to Conduct PIA:**

- Before processing new categories of personal data
- When deploying new AI systems
- Before significant system changes
- After data breaches

**PIA Template:**

```markdown
# Privacy Impact Assessment

## 1. Project Overview
- **Project Name**: [Name]
- **Project Owner**: [Team/Person]
- **Date**: [Date]

## 2. Data Processing
### 2.1 Data Categories
- [ ] Personal identifiers (name, email)
- [ ] Sensitive data (health, financial)
- [ ] Biometric data
- [ ] Criminal records

### 2.2 Data Sources
- [ ] Direct collection from users
- [ ] Third-party data providers
- [ ] Publicly available data
- [ ] Inferred data

### 2.3 Processing Purposes
- [ ] Model training
- [ ] Model inference
- [ ] Analytics
- [ ] User personalization

## 3. Privacy Risks
### 3.1 Identification Risk
- Risk Level: [Low/Medium/High]
- Mitigation: [Describe]

### 3.2 Data Linkage Risk
- Risk Level: [Low/Medium/High]
- Mitigation: [Describe]

### 3.3 Re-identification Risk
- Risk Level: [Low/Medium/High]
- Mitigation: [Describe]

## 4. Compliance
- [ ] GDPR compliant
- [ ] CCPA compliant
- [ ] HIPAA compliant (if applicable)

## 5. Mitigation Plan
1. [Action item 1]
2. [Action item 2]
3. [Action item 3]

## 6. Approval
- Privacy Officer: [Signature/Date]
- Data Protection Officer: [Signature/Date]
- Project Lead: [Signature/Date]
```

### Privacy CLI Commands

```bash
# Assess privacy risks
mahavishnu ethics privacy assess \
    --dataset ./data/customers.csv \
    --pii name \
    --pii email \
    --pii ssn \
    --technique differential_privacy \
    --output ./privacy_assessment.json

# Anonymize dataset
mahavishnu ethics privacy anonymize \
    --input ./data/raw/customers.csv \
    --output ./data/anonymized/customers.csv \
    --technique differential_privacy \
    --epsilon 1.0 \
    --pii name \
    --pii email \
    --pii ssn

# Manage consent
mahavishnu ethics privacy consent \
    --action record \
    --user user123 \
    --purpose "model_training"

mahavishnu ethics privacy consent \
    --action check \
    --user user123

mahavishnu ethics privacy consent \
    --action audit
```

---

## AI Safety Monitoring

### Safety Dimensions

#### 1. Adversarial Robustness

**Threat:** Malicious actors craft inputs to cause model failures.

**Testing:**

```bash
mahavishnu ethics safety evaluate \
    --model ./models/chatbot.pkl \
    --suite adversarial \
    --samples 5000 \
    --output ./safety_report.json
```

**Defense:**

```python
# Adversarial training
import tensorflow as tf

# Create adversarial examples
adv_model = tf.keras.models.clone_model(model)
adv_model.set_weights(model.get_weights())

# Train on adversarial examples
for epoch in range(epochs):
    for x_batch, y_batch in dataset:
        # Generate adversarial examples
        with tf.GradientTape() as tape:
            loss = tf.keras.losses.sparse_categorical_crossentropy(
                y_batch, adv_model(x_batch)
            )

        gradient = tape.gradient(loss, adv_model.trainable_variables)
        # Create adversarial perturbation
        x_adv = x_batch + 0.01 * tf.sign(gradient)

        # Train on adversarial examples
        adv_model.train_on_batch(x_adv, y_batch)
```

#### 2. Toxic Content Generation

**Threat:** Model generates harmful, offensive, or dangerous content.

**Testing:**

```python
# Toxicity detection
from detoxify import Detoxify

def check_toxicity(text):
    """Check if text is toxic."""
    results = Detoxify('original').predict(text)

    return {
        'toxicity': results['toxicity'],
        'severe_toxicity': results['severe_toxicity'],
        'obscene': results['obscene'],
        'threat': results['threat'],
        'insult': results['insult'],
        'identity_attack': results['identity_attack']
    }

# Filter model outputs
def safe_generate(prompt, model):
    """Generate with toxicity filtering."""
    response = model.generate(prompt)

    toxicity = check_toxicity(response)
    if max(toxicity.values()) > 0.5:
        # Refuse to generate
        return "I cannot provide this response."
    else:
        return response
```

#### 3. Hallucination Detection

**Threat:** Model generates plausible but factually incorrect information.

**Testing:**

```python
# Fact-checking with retrieval
def detect_hallucination(response, knowledge_base):
    """Check if response is grounded in facts."""

    # Extract claims from response
    claims = extract_claims(response)

    # Verify each claim against knowledge base
    hallucinations = []
    for claim in claims:
        if not verify_claim(claim, knowledge_base):
            hallucinations.append(claim)

    return len(hallucinations) / len(claims)
```

**Mitigation:**

```python
# Retrieval-augmented generation (RAG)
from sentence_transformers import SentenceTransformer
import faiss

# Create knowledge base index
embedder = SentenceTransformer('all-MiniLM-L6-v2')
kb_embeddings = embedder.encode(knowledge_base)
index = faiss.IndexFlatL2(kb_embeddings.shape[1])
index.add(kb_embeddings)

# Retrieve relevant context
def retrieve_context(query, k=3):
    """Retrieve relevant knowledge base entries."""
    query_embedding = embedder.encode([query])
    distances, indices = index.search(query_embedding, k)
    return [knowledge_base[i] for i in indices[0]]

# Generate with context
def grounded_generate(prompt, model):
    """Generate with factual grounding."""
    context = retrieve_context(prompt)

    # Augment prompt with retrieved context
    grounded_prompt = f"""
    Context: {context}

    Question: {prompt}

    Answer based only on the provided context:
    """

    return model.generate(grounded_prompt)
```

#### 4. Jailbreak Prevention

**Threat:** Users craft prompts to bypass safety guardrails.

**Detection:**

```python
# Known jailbreak patterns
jailbreak_patterns = [
    r"ignore (all )?(previous|above) instructions",
    r"forget everything",
    r"you are now (uncensored|unrestricted)",
    r"pretend to be.*?(evil|malicious)",
    r"DAN mode",
    r"developer mode"
]

def detect_jailbreak(prompt):
    """Detect potential jailbreak attempts."""
    import re

    for pattern in jailbreak_patterns:
        if re.search(pattern, prompt, re.IGNORECASE):
            return True, f"Pattern matched: {pattern}"

    return False, None
```

**Response:**

```python
def safe_handle_prompt(prompt, model):
    """Handle prompt with jailbreak detection."""
    is_jailbreak, reason = detect_jailbreak(prompt)

    if is_jailbreak:
        # Log attempt
        log_security_incident("jailbreak_attempt", prompt, reason)

        # Refuse
        return "I cannot comply with this request."

    # Normal processing
    return model.generate(prompt)
```

### Real-Time Safety Monitoring

```bash
# Continuous monitoring
mahavishnu ethics safety monitor \
    --model ./models/assistant.pkl \
    --logs ./logs/predictions.jsonl \
    --window 24h \
    --threshold 0.75 \
    --continuous
```

**Monitoring Metrics:**

- Toxicity rate (target: < 0.1%)
- Hallucination rate (target: < 5%)
- Jailbreak attempts (target: 0)
- Adversarial success rate (target: < 1%)
- User flag rate (target: < 0.5%)

**Alerting:**

```python
# Alert on safety incidents
def check_safety_metrics(metrics):
    """Check if safety metrics trigger alerts."""

    alerts = []

    if metrics['toxicity_rate'] > 0.001:
        alerts.append({
            'severity': 'critical',
            'metric': 'toxicity_rate',
            'value': metrics['toxicity_rate'],
            'threshold': 0.001
        })

    if metrics['hallucination_rate'] > 0.05:
        alerts.append({
            'severity': 'warning',
            'metric': 'hallucination_rate',
            'value': metrics['hallucination_rate'],
            'threshold': 0.05
        })

    # Send alerts
    for alert in alerts:
        send_alert(
            severity=alert['severity'],
            message=f"Safety threshold exceeded: {alert['metric']} = {alert['value']}",
            webhook=os.getenv('SLACK_WEBHOOK')
        )
```

### Red Team Testing

```bash
# Conduct red team exercise
mahavishnu ethics safety red-team \
    --model ./models/assistant.pkl \
    --attack prompt_injection \
    --attack jailbreak \
    --attack data_extraction \
    --duration 7200 \
    --output ./redteam_report.json
```

**Red Team Checklist:**

- [ ] Prompt injection attempts
- [ ] Jailbreak attempts
- [ ] Data extraction attempts
- [ ] Adversarial examples
- [ ] Toxic content generation
- [ ] Hallucination triggers
- [ ] Role-playing attacks
- [ ] Social engineering attempts

---

## Regulatory Compliance

### Compliance Frameworks

#### GDPR (General Data Protection Regulation)

**Key Requirements for AI:**

| Requirement | Description | Implementation |
|-------------|-------------|----------------|
| **Lawful Basis** | Legal basis for processing | Consent, contract, legitimate interest |
| **Right to Explanation** | Explain automated decisions | SHAP/LIME explanations |
| **Data Minimization** | Collect only necessary data | Remove unused features |
| **Purpose Limitation** | Use data only for stated purpose | Separate data for different purposes |
| **Privacy by Design** | Build privacy into system | Differential privacy, anonymization |
| **DPIA** | Data protection impact assessment | Conduct before high-risk processing |
| **Breach Notification** | Notify within 72 hours | Implement breach detection |

**GDPR Compliance Checklist:**

```bash
mahavishnu ethics compliance check \
    --model ./models/credit_scoring.pkl \
    --framework gdpr \
    --detailed \
    --output ./gdpr_compliance.json
```

**Documentation Required:**

1. **Records of Processing Activities (ROPA):**
   - Data categories
   - Purposes of processing
   - Data recipients
   - Retention periods
   - Security measures

2. **Legitimate Interest Assessment (LIA):**
   - Purpose of processing
   - Necessity of processing
   - Balancing test (individual rights vs. legitimate interests)
   - Safeguards for individuals

3. **Data Protection Impact Assessment (DPIA):**
   - Systematic description of processing
   - Purpose of processing (including legitimate interests)
   - Assessment of necessity and proportionality
   - Risks to individuals
   - Mitigation measures

#### EU AI Act

**Risk Classification:**

| Risk Level | Examples | Requirements |
|------------|----------|--------------|
| **Unacceptable** | Social scoring, real-time biometrics (with exceptions) | Banned |
| **High** | Recruitment, credit scoring, medical diagnosis | Strict compliance: conformity assessment, quality management, technical documentation, human oversight, accuracy, robustness, cybersecurity |
| **Limited** | Deepfake detection, emotion recognition | Transparency obligations |
| **Minimal** | Spam filters, video games | No specific requirements |

**High-Risk AI Requirements:**

```bash
mahavishnu ethics compliance check \
    --model ./models/hiring.pkl \
    --framework eu_ai_act \
    --detailed \
    --output ./eu_ai_act_compliance.json
```

**Requirements:**

1. **Risk Management System:** Continuous risk identification and mitigation
2. **Data Governance:** Data quality, relevance, and bias mitigation
3. **Technical Documentation:** Detailed design, development, and testing docs
4. **Record Keeping:** Automatic logging of events
5. **Transparency:** Provide information to users
6. **Human Oversight:** Human-in-the-loop for high-stakes decisions
7. **Accuracy:** Metrics for accuracy, robustness, cybersecurity
8. **Conformity Assessment:** Third-party certification before deployment

#### SOC 2 (Service Organization Control 2)

**Trust Principles:**

| Principle | Description | AI-Specific Considerations |
|-----------|-------------|---------------------------|
| **Security** | Protect against unauthorized access | Model access controls, authentication |
| **Availability** | System is available as promised | Model uptime, failover mechanisms |
| **Processing Integrity** | Data is processed accurately | Model accuracy monitoring, data validation |
| **Confidentiality** | Information is protected | Data encryption, differential privacy |
| **Privacy** | Personal information is protected | Consent management, data minimization |

**SOC 2 Compliance:**

```bash
mahavishnu ethics compliance check \
    --model ./models/fraud_detection.pkl \
    --framework soc2 \
    --detailed \
    --output ./soc2_compliance.json
```

#### ISO 42001:2023 (AI Management System)

**Key Requirements:**

1. **AI Policy:** Statement of commitment to responsible AI
2. **Risk Assessment:** AI system impact assessment
3. **Risk Treatment:** Mitigation plans for identified risks
4. **Controls:** Technical and organizational controls
5. **Monitoring:** Continuous monitoring of AI systems
6. **Internal Audit:** Regular compliance audits
7. **Management Review:** Executive oversight of AI governance
8. **Continual Improvement:** Ongoing improvement of AI management

```bash
mahavishnu ethics compliance check \
    --model ./models/predictive_maintenance.pkl \
    --framework iso_42001 \
    --detailed \
    --output ./iso42001_compliance.json
```

### Compliance Workflow

#### Step 1: Identify Applicable Frameworks

```python
# Determine which frameworks apply
def identify_frameworks(model_use_case, data_type, region):
    """Identify applicable compliance frameworks."""

    frameworks = []

    # Region-specific
    if region in ["EU", "Europe"]:
        frameworks.extend(["gdpr", "eu_ai_act"])

    if region in ["US", "United States", "California"]:
        frameworks.append("ccpa")

    # Data-type specific
    if data_type == "health":
        frameworks.append("hipaa")

    if data_type == "financial":
        frameworks.append("soc2")

    # Use-case specific
    if model_use_case in ["hiring", "credit", "insurance"]:
        frameworks.append("eu_ai_act")  # High-risk under EU AI Act

    return list(set(frameworks))  # Deduplicate

# Example
frameworks = identify_frameworks(
    model_use_case="credit_scoring",
    data_type="financial",
    region="EU"
)
# Output: ['gdpr', 'eu_ai_act', 'soc2']
```

#### Step 2: Conduct Compliance Check

```bash
mahavishnu ethics compliance check \
    --model ./models/credit_scoring.pkl \
    --framework gdpr \
    --framework eu_ai_act \
    --framework soc2 \
    --detailed \
    --output ./compliance_report.json
```

#### Step 3: Address Gaps

```python
# Review compliance gaps
with open("compliance_report.json") as f:
    report = json.load(f)

for framework, result in report["frameworks"].items():
    if result["critical_gaps"]:
        print(f"\n{framework.upper()} - Critical Gaps:")
        for gap in result["critical_gaps"]:
            print(f"  ⚠️ {gap}")
            # Create remediation task
            create_task(gap, priority="critical")
```

#### Step 4: Pre-Deployment Approval

```bash
mahavishnu ethics compliance approve \
    --model ./models/credit_scoring.pkl \
    --requester "ai-team@company.com" \
    --env production \
    --framework gdpr \
    --framework eu_ai_act \
    --comments "All gaps addressed, version 2.0"
```

#### Step 5: Ongoing Monitoring

```bash
# Continuous compliance monitoring
mahavishnu ethics compliance audit \
    --model ./models/credit_scoring.pkl \
    --type full \
    --start 2025-01-01 \
    --end 2025-02-01 \
    --output ./monthly_audit.json
```

### Compliance Documentation

**Required Documentation:**

1. **Model Card:** Model purpose, limitations, intended use
2. **Data Sheet:** Dataset sources, collection methods, preprocessing
3. **Model Report:** Training details, performance metrics, fairness
4. **DPIA:** Data protection impact assessment (GDPR)
5. **Conformity Assessment:** Technical documentation (EU AI Act)
6. **Risk Assessment:** ISO 42001 risk assessment
7. **Audit Trail:** Model decisions, changes, incidents

---

## Pre-Deployment Checklist

### Critical Checks (Must Pass)

- [ ] **Bias Detection Completed**
  - Demographic parity ≥ 0.8
  - Equal opportunity ≥ 0.8
  - Disparate impact ≥ 0.8
  - No critical bias findings

- [ ] **Explainability Implemented**
  - Local explanations available (SHAP/LIME)
  - Global feature importance documented
  - Explanation quality validated

- [ ] **Privacy Protected**
  - PII identified and protected
  - Differential privacy applied (ε ≤ 1.0)
  - Consent management configured
  - Data minimization verified

- [ ] **Safety Validated**
  - Adversarial robustness tested
  - Toxic content generation < 0.1%
  - Hallucination rate < 5%
  - Jailbreak resistance verified

- [ ] **Compliance Verified**
  - GDPR requirements met (score ≥ 0.8)
  - EU AI Act requirements met (if applicable)
  - Industry-specific regulations met (HIPAA, SOC2, etc.)
  - Documentation complete

### Important Checks (Should Pass)

- [ ] **Human-in-the-Loop**
  - High-stakes decisions flagged for review
  - Review process documented
  - Reviewers trained

- [ ] **Monitoring Configured**
  - Real-time safety metrics tracked
  - Alert thresholds configured
  - Incident response plan defined

- [ ] **Rollback Plan**
  - Previous model version identified
  - Rollback procedure documented
  - Rollback tested

- [ ] **Documentation Complete**
  - Model card created
  - Data sheet created
  - Technical documentation complete

### Nice to Have

- [ ] **Stakeholder Review**
  - Legal review completed
  - Ethics review completed
  - User group feedback collected

- [ ] **Performance Validation**
  - A/B test results available
  - Performance metrics meet SLA
  - Load testing completed

- [ ] **Training**
  - Developers trained on AI ethics
  - Reviewers trained on bias detection
  - Users educated on AI limitations

### Deployment Approval Command

```bash
# Interactive approval with automatic checks
mahavishnu ethics compliance approve \
    --model ./models/production_v2.pkl \
    --requester "ai-team@company.com" \
    --env production \
    --framework gdpr \
    --framework eu_ai_act
```

**Output:**

```
Pre-Deployment Checklist:
  ✓ Bias detection completed
  ✓ Explainability implemented
  ✓ Privacy impact assessment
  ✓ Safety evaluation passed
  ✓ Compliance verified
  ✓ Documentation complete
  ✓ Monitoring configured
  ✗ Rollback plan defined

Overall Score: 7/8 (87.5%)
Status: APPROVED with warnings

Warnings:
  - Rollback plan not documented
  - Recommended: Define rollback procedure before production deployment

Deployment Approval ID: APPROVAL-20250205-143022
Approved by: ai-team@company.com
Environment: production
Timestamp: 2025-02-05T14:30:22Z
```

---

## Training Materials

### AI Ethics Training for Developers

**Module 1: Understanding AI Ethics (1 hour)**

**Learning Objectives:**
- Understand why AI ethics matters
- Identify key ethical principles
- Recognize common ethical pitfalls

**Topics:**

1. **Why AI Ethics Matters**
   - Real-world AI failures (Amazon hiring, COMPAS recidivism)
   - Legal and regulatory landscape
   - Business case for ethical AI

2. **Core Ethical Principles**
   - Fairness and non-discrimination
   - Transparency and explainability
   - Privacy and data protection
   - Accountability and oversight
   - Safety and reliability

3. **Common Ethical Pitfalls**
   - Data bias
   - Algorithmic unfairness
   - Lack of transparency
   - Privacy violations
   - Safety failures

**Module 2: Bias Detection and Mitigation (2 hours)**

**Learning Objectives:**
- Identify sources of bias in AI systems
- Measure fairness metrics
- Apply bias mitigation techniques

**Topics:**

1. **Types of Bias**
   - Selection bias
   - Measurement bias
   - Algorithmic bias
   - Label bias

2. **Fairness Metrics**
   - Demographic parity
   - Equal opportunity
   - Disparate impact
   - Calibration

3. **Mitigation Techniques**
   - Preprocessing (reweighting, resampling)
   - In-processing (adversarial debiasing)
   - Post-processing (threshold adjustment)

**Hands-on Exercise:**

```python
# Exercise: Detect and mitigate bias
# File: exercises/bias_detection.py

import pandas as pd
from fairlearn.metrics import demographic_parity_difference

# Load dataset
df = pd.read_csv('data/credit_applications.csv')

# Train model
model = train_model(df)

# Detect bias
dp_diff = demographic_parity_difference(
    df['approved'], model.predict(df[features]),
    sensitive_features=df['gender']
)

print(f"Demographic Parity Difference: {dp_diff:.3f}")

if dp_diff > 0.05:
    print("⚠️ Bias detected! Apply mitigation...")
    # Apply mitigation
    model = apply_mitigation(model, df, 'gender')
```

**Module 3: Explainability (1.5 hours)**

**Learning Objectives:**
- Explain AI decisions using multiple methods
- Choose appropriate explanation techniques
- Balance accuracy and interpretability

**Topics:**

1. **Explanation Methods**
   - SHAP (local and global)
   - LIME (local)
   - Feature importance (global)
   - Counterfactual explanations

2. **When to Use Which Method**
   - Decision trees vs. neural networks
   - Local vs. global explanations
   - Technical vs. non-technical audiences

3. **Communication**
   - Explaining technical concepts to non-technical stakeholders
   - Visualizing explanations
   - Setting appropriate expectations

**Module 4: Privacy Protection (1.5 hours)**

**Learning Objectives:**
- Apply privacy-preserving techniques
- Conduct privacy impact assessments
- Comply with privacy regulations

**Topics:**

1. **Privacy Techniques**
   - Differential privacy
   - K-anonymity
   - Pseudonymization
   - Federated learning

2. **Regulatory Compliance**
   - GDPR requirements
   - CCPA requirements
   - HIPAA requirements (if applicable)

3. **Privacy Impact Assessment**
   - When to conduct PIA
   - PIA process
   - Risk mitigation

**Module 5: AI Safety (1 hour)**

**Learning Objectives:**
- Identify safety risks in AI systems
- Implement safety monitoring
- Respond to safety incidents

**Topics:**

1. **Safety Dimensions**
   - Adversarial robustness
   - Toxic content generation
   - Hallucination
   - Jailbreak attempts

2. **Monitoring and Alerting**
   - Real-time safety metrics
   - Alert thresholds
   - Incident response

3. **Red Team Testing**
   - Planning red team exercises
   - Common attack patterns
   - Vulnerability remediation

### Bias Awareness Training

**Exercise 1: Bias Identification (30 minutes)**

**Scenario:** You're developing a hiring recommendation system.

**Task:** Identify potential sources of bias in this scenario:

1. **Training Data:** Historical hiring decisions from the last 5 years
2. **Features:** Resume text, education, work experience, skills, referrals
3. **Target Variable:** Hired or not hired

**Discussion Questions:**
- What biases might exist in historical hiring decisions?
- Which features might be proxies for protected attributes?
- How could we measure fairness in this system?

**Exercise 2: Measuring Fairness (45 minutes)**

**Task:** Calculate fairness metrics for a credit scoring model.

```python
# Given: model predictions and test data
y_true = test_data['approved']
y_pred = model.predict(test_data[features])
gender = test_data['gender']

# Calculate metrics
from fairlearn.metrics import demographic_parity_difference
from fairlearn.metrics import equalized_odds_difference

dp_diff = demographic_parity_difference(y_true, y_pred, gender)
eo_diff = equalized_odds_difference(y_true, y_pred, gender)

print(f"Demographic Parity Difference: {dp_diff:.3f}")
print(f"Equalized Odds Difference: eo_diff:.3f}")

# Questions:
# 1. Is this model fair? (Threshold: < 0.05)
# 2. If not, what mitigation technique would you apply?
# 3. How would you verify the mitigation worked?
```

### Privacy Training

**Exercise 1: PII Identification (30 minutes)**

**Task:** Identify PII in the following dataset and classify by sensitivity:

| Field | PII Type | Sensitivity |
|-------|----------|-------------|
| name | ? | ? |
| email | ? | ? |
| ip_address | ? | ? |
| user_id | ? | ? |
| age | ? | ? |
| zip_code | ? | ? |
| credit_score | ? | ? |

**Exercise 2: Privacy Techniques (60 minutes)**

**Task:** Apply differential privacy to a dataset.

```python
# Given: dataset with income data
import opendp.prelude as dp

dp.enable_features("floating-point", "contrib")

# Task 1: Calculate private mean (ε=1.0)
context = dp.Context.compositor(
    data=dp.vector_domain(dp.atom_domain(T=float)),
    privacy_unit=dp.unit_of(dp.contributions_max=1),
    privacy_loss=dp.loss_of(dp.epsilon=1.0, delta=1e-6)
)

private_mean = context.query().laplace().mean().release()

# Task 2: Compare private vs. non-private mean
non_private_mean = df['income'].mean()

print(f"Private mean: {private_mean}")
print(f"Non-private mean: {non_private_mean}")
print(f"Difference: {abs(private_mean - non_private_mean)}")

# Questions:
# 1. How much accuracy did we trade for privacy?
# 2. What if we use ε=0.1? How does it change?
# 3. When should we use strong privacy (low ε) vs. weak privacy (high ε)?
```

### Best Practices Guide

#### Development Phase

1. **Start with Interpretable Models**
   - Use linear regression, logistic regression, decision trees when possible
   - Only use complex models if accuracy gain justifies interpretability loss

2. **Collect Diverse Training Data**
   - Ensure representation across all demographic groups
   - Avoid historical bias in training data
   - Document data sources and limitations

3. **Build Fairness into Development**
   - Include fairness metrics in model evaluation
   - Test for bias during development, not after deployment
   - Use bias mitigation techniques proactively

#### Deployment Phase

1. **Implement Human-in-the-Loop**
   - Flag low-confidence predictions for review
   - Require human approval for high-stakes decisions
   - Establish appeals process

2. **Configure Monitoring**
   - Track fairness metrics in production
   - Monitor for drift and degradation
   - Set up alerting for safety incidents

3. **Document Everything**
   - Create model cards documenting purpose and limitations
   - Maintain audit trail of model decisions
   - Document deployment decisions and rationale

#### Operation Phase

1. **Continuous Monitoring**
   - Regular bias audits (monthly or quarterly)
   - Safety metric tracking
   - User feedback collection

2. **Incident Response**
   - Define incident severity levels
   - Establish response procedures
   - Conduct post-incident reviews

3. **Regular Updates**
   - Retrain models with new data
   - Update fairness baselines
   - Refresh documentation

---

## Case Studies

### Case Study 1: Amazon Hiring AI (2018)

**Problem:** Amazon developed an AI recruiting tool that showed bias against women.

**Root Causes:**
1. **Training Data:** Trained on 10 years of hiring data, which reflected male-dominated tech industry
2. **Feature Selection:** Model learned to downgrad eresumes with "women's college" or "women's soccer"
3. **Lack of Testing:** No fairness testing before deployment

**Consequences:**
- Project scrapped after internal discovery
- Reputational damage
- $ Millions wasted

**Lessons Learned:**
1. **Test for bias early and often**
2. **Diverse training data is critical**
3. **Feature engineering can encode bias**
4. **Human oversight is essential**

**Prevention with Mahavishnu:**

```bash
# Before deployment
mahavishnu ethics bias detect \
    --model ./models/hiring.pkl \
    --dataset ./data/applications.csv \
    --attribute gender \
    --attribute race \
    --threshold 0.8

# If bias detected
mahavishnu ethics bias mitigate \
    --model ./models/hiring.pkl \
    --dataset ./data/applications.csv \
    --technique adversarial \
    --target 0.90
```

### Case Study 2: COMPAS Recidivism (2016)

**Problem:** COMPAS risk assessment tool showed racial bias in predicting recidivism.

**Root Causes:**
1. **Algorithmic Bias:** Objective function prioritized overall accuracy over fairness
2. **Label Bias:** Training labels (rearrest rates) reflected biased policing
3. **Lack of Transparency:** Proprietary algorithm, no explanation

**Consequences:**
- ProPublica investigation revealed bias
- Lawsuits filed
- Widespread criticism

**Key Findings:**
- False positive rate: African American defendants 2x higher than white defendants
- False negative rate: White defendants 2x higher than African American defendants

**Lessons Learned:**
1. **Fairness metrics matter as much as accuracy**
2. **Transparency enables accountability**
3. **Human oversight required for high-stakes decisions**

**Prevention with Mahavishnu:**

```bash
# Fairness evaluation
mahavishnu ethics bias detect \
    --model ./models/recidivism.pkl \
    --dataset ./data/defendants.csv \
    --attribute race \
    --threshold 0.8

# Explainability
mahavishnu ethics explain decision \
    --model ./models/recidivism.pkl \
    --input '{"age': 35, 'prior_offenses': 2, 'race': 'African American'}' \
    --method shap \
    --top 10
```

### Case Study 3: Google Photos (2015)

**Problem:** Image labeling system labeled African American users as "gorillas."

**Root Causes:**
1. **Training Data Bias:** Underrepresentation of darker-skinned individuals in training data
2. **Lack of Testing:** Insufficient testing across demographic groups
3. **No Safety Monitoring:** No monitoring for offensive or harmful outputs

**Consequences:**
- Public apology required
- Immediate removal of label category
- Reputational damage
- Loss of user trust

**Lessons Learned:**
1. **Diverse training data is essential**
2. **Test across all demographic groups**
3. **Implement safety monitoring**
4. **Human review before deployment**

**Prevention with Mahavishnu:**

```bash
# Safety evaluation
mahavishnu ethics safety evaluate \
    --model ./models/image_labeling.pkl \
    --suite comprehensive \
    --output ./safety_report.json

# Red team testing
mahavishnu ethics safety red-team \
    --model ./models/image_labeling.pkl \
    --attack adversarial \
    --duration 3600
```

### Case Study 4: Healthcare Algorithm (2019)

**Problem:** Optum healthcare algorithm prioritized white patients over Black patients for extra care resources.

**Root Causes:**
1. **Proxy Variable:** Used healthcare costs as proxy for health needs
2. **Structural Bias:** Healthcare system spends less on Black patients, leading to lower costs despite equal need
3. **Lack of Fairness Testing**: No fairness metrics evaluated

**Consequences:**
- Study published in Science (2019)
- Algorithm required significant rework
- $ Billions in misallocated resources

**Lessons Learned:**
1. **Be careful with proxy variables**
2. **Understand structural bias in data**
3. **Evaluate fairness metrics relevant to use case**

**Prevention with Mahavishnu:**

```bash
# Fairness evaluation
mahavishnu ethics bias detect \
    --model ./models/healthcare_prioritization.pkl \
    --dataset ./data/patients.csv \
    --attribute race \
    --threshold 0.8

# Explainability
mahavishnu ethics explain global \
    --model ./models/healthcare_prioritization.pkl \
    --dataset ./data/patients.csv \
    --method feature_importance \
    --output ./explanations/healthcare.json
```

---

## Best Practices

### Model Development Lifecycle

#### Phase 1: Planning

```
[Define Use Case] → [Identify Risks] → [Select Frameworks] → [Set Metrics]
```

**Checklist:**
- [ ] Define clear, ethical use case
- [ ] Conduct risk assessment
- [ ] Identify applicable regulations (GDPR, EU AI Act, HIPAA, etc.)
- [ ] Set fairness thresholds (≥ 0.8)
- [ ] Define privacy requirements (ε budget)
- [ ] Plan for human oversight

#### Phase 2: Data Collection

```
[Collect Data] → [Audit for Bias] → [Diversify] → [Document]
```

**Checklist:**
- [ ] Audit training data for representational bias
- [ ] Ensure diverse representation across protected groups
- [ ] Document data sources and limitations
- [ ] Obtain proper consent for data use
- [ ] Minimize PII collection

#### Phase 3: Model Development

```
[Start Simple] → [Test Fairness] → [Mitigate Bias] → [Iterate]
```

**Checklist:**
- [ ] Start with interpretable models (linear, decision trees)
- [ ] Test for bias during development
- [ ] Apply bias mitigation techniques
- [ ] Document model architecture and decisions
- [ ] Maintain model version control

#### Phase 4: Testing

```
[Unit Tests] → [Fairness Tests] → [Safety Tests] → [Explainability Tests]
```

**Checklist:**
- [ ] Unit tests pass (accuracy, precision, recall)
- [ ] Fairness metrics meet thresholds (≥ 0.8)
- [ ] Safety evaluation completed
- [ ] Explainability validated
- [ ] Privacy impact assessment completed

#### Phase 5: Deployment

```
[Pre-Deployment Check] → [Approve] → [Deploy] → [Monitor]
```

**Checklist:**
- [ ] Pre-deployment checklist completed
- [ ] Compliance approval obtained
- [ ] Monitoring configured
- [ ] Rollback plan defined
- [ ] Incident response team notified

#### Phase 6: Monitoring

```
[Track Metrics] → [Audit Regularly] → [Retrain as Needed] → [Update Docs]
```

**Checklist:**
- [ ] Real-time fairness monitoring
- [ ] Safety metric tracking
- [ ] Regular bias audits (monthly/quarterly)
- [ ] User feedback collection
- [ ] Documentation updated

### Documentation Standards

#### Model Card Template

```markdown
# Model Card: [Model Name]

## Model Details
- **Model Name**: [Name]
- **Version**: [Version]
- **Model Type**: [Type: classification, regression, etc.]
- **Model Owner**: [Team/Person]
- **Last Updated**: [Date]

## Intended Use
- **Primary Use Case**: [Description]
- **Intended Users**: [Who should use this model]
- **Out-of-Scope Uses**: [What this model should NOT be used for]

## Model Performance
- **Accuracy**: [Metric]
- **Precision**: [Metric]
- **Recall**: [Metric]
- **F1 Score**: [Metric]
- **AUC-ROC**: [Metric]

## Fairness Metrics
- **Demographic Parity**: [Score]
- **Equal Opportunity**: [Score]
- **Disparate Impact**: [Score]
- **Calibration**: [Score]

## Limitations
- [Known limitation 1]
- [Known limitation 2]
- [Known limitation 3]

## Ethical Considerations
- [Potential risks]
- [Mitigation measures]
- [Human oversight requirements]

## Training Data
- **Data Sources**: [Where data came from]
- **Time Period**: [When data was collected]
- **Sample Size**: [Number of samples]
- **Protected Attributes**: [Gender, race, age, etc.]

## Monitoring
- **Production Metrics**: [What's tracked]
- **Alert Thresholds**: [When to alert]
- **Last Audit**: [Date]
- **Next Audit**: [Date]
```

#### Data Sheet Template

```markdown
# Data Sheet: [Dataset Name]

## Dataset Overview
- **Dataset Name**: [Name]
- **Version**: [Version]
- **Creator**: [Team/Person]
- **Last Updated**: [Date]

## Data Collection
- **Collection Method**: [How data was collected]
- **Time Period**: [When data was collected]
- **Sample Size**: [Number of samples]
- **Geographic Coverage**: [Where data was collected]

## Data Composition
- **Features**: [List of features]
- **Labels**: [What's being predicted]
- **Protected Attributes**: [Gender, race, age, etc.]
- **Missing Values**: [Percentage and handling]

## Data Distribution
- **Demographic Breakdown**: [By protected attributes]
- **Class Balance**: [Imbalance metrics]
- **Outliers**: [How identified and handled]

## Preprocessing
- **Cleaning Steps**: [What was done]
- **Feature Engineering**: [New features created]
- **Normalization**: [Scaling, encoding]
- **Train/Validation/Test Split**: [How split]

## Bias Assessment
- **Representational Bias**: [Assessment]
- **Label Bias**: [Assessment]
- **Historical Bias**: [Assessment]
- **Mitigation**: [Steps taken]

## Privacy
- **PII Present**: [Yes/No]
- **PII Types**: [What PII exists]
- **Anonymization**: [Techniques used]
- **Consent**: [Consent status]

## Intended Use
- **Primary Use**: [What this data is for]
- **Prohibited Uses**: [What this data should NOT be used for]
- **High-Risk Uses**: [Risks of misuse]

## Maintenance
- **Update Frequency**: [How often updated]
- **Known Issues**: [Current limitations]
- **Future Improvements**: [Planned enhancements]
```

### Team Responsibilities

#### AI Engineers

**Responsibilities:**
- Build fairness into model development
- Test for bias during development
- Implement privacy-preserving techniques
- Create model cards and documentation

**Required Skills:**
- Bias detection and mitigation
- Explainability techniques
- Privacy-preserving ML
- Regulatory compliance basics

#### Data Scientists

**Responsibilities:**
- Audit training data for bias
- Ensure diverse representation
- Document data sources and limitations
- Conduct fairness analysis

**Required Skills:**
- Data ethics
- Fairness metrics
- Data auditing
- Privacy impact assessment

#### ML Engineers (MLOps)

**Responsibilities:**
- Implement monitoring systems
- Configure alerting
- Maintain audit trails
- Deploy safety measures

**Required Skills:**
- Real-time monitoring
- Incident response
- Security best practices
- Deployment automation

#### Product Managers

**Responsibilities:**
- Define ethical use cases
- Assess product risks
- Prioritize ethical AI features
- Ensure user transparency

**Required Skills:**
- AI ethics literacy
- Risk assessment
- Regulatory landscape
- User empathy

#### Legal/Compliance

**Responsibilities:**
- Interpret regulations (GDPR, EU AI Act, etc.)
- Review compliance documentation
- Approve deployments
- Manage incident response

**Required Skills:**
- AI regulations
- Data protection law
- Risk assessment
- Documentation review

---

## Troubleshooting

### Common Issues and Solutions

#### Issue 1: High Bias Detected

**Symptom:** Bias metrics below threshold (e.g., demographic parity = 0.65)

**Diagnosis:**

```bash
# Detailed bias analysis
mahavishnu ethics bias detect \
    --model ./models/model.pkl \
    --dataset ./data/test.csv \
    --attribute gender \
    --attribute race \
    --output ./bias_detailed.json
```

**Solutions:**

1. **Check training data:**
   ```python
   # Check for representational bias
   print(df['gender'].value_counts(normalize=True))
   print(df['race'].value_counts(normalize=True))

   # Target: Each group ≥ 20% representation
   ```

2. **Apply bias mitigation:**
   ```bash
   mahavishnu ethics bias mitigate \
       --model ./models/model.pkl \
       --dataset ./data/train.csv \
       --technique adversarial \
       --target 0.90 \
       --output ./models/model_fair.pkl
   ```

3. **Feature engineering:**
   ```python
   # Remove proxy variables for protected attributes
   features_to_remove = ['zip_code', 'proxy_var']
   X = X.drop(columns=features_to_remove)
   ```

#### Issue 2: Low Explainability Score

**Symptom:** Explanations are unclear or inconsistent

**Diagnosis:**

```bash
# Test explanation quality
mahavishnu ethics explain decision \
    --model ./models/model.pkl \
    --input '{"feature1": 100, "feature2": 50}' \
    --method shap \
    --top 10
```

**Solutions:**

1. **Simplify model:**
   ```python
   # Replace complex model with interpretable alternative
   from sklearn.linear_model import LogisticRegression
   model = LogisticRegression()  # Instead of neural network
   ```

2. **Improve explanations:**
   ```python
   # Use multiple explanation methods
   import shap
   import lime

   shap_explainer = shap.TreeExplainer(model)
   lime_explainer = lime.lime_tabular.LimeTabularExplainer(...)

   # Compare explanations
   ```

3. **Feature engineering:**
   ```python
   # Use meaningful feature names
   feature_names = [
       'customer_tenure_years',  # Instead of 'f1'
       'payment_history_score',  # Instead of 'f2'
   ]
   ```

#### Issue 3: Privacy Risk Too High

**Symptom:** Re-identification risk score > 0.7

**Diagnosis:**

```bash
mahavishnu ethics privacy assess \
    --dataset ./data/customers.csv \
    --technique differential_privacy \
    --output ./privacy_risk.json
```

**Solutions:**

1. **Apply differential privacy:**
   ```bash
   mahavishnu ethics privacy anonymize \
       --input ./data/customers.csv \
       --output ./data/customers_private.csv \
       --technique differential_privacy \
       --epsilon 1.0
   ```

2. **Data minimization:**
   ```python
   # Remove unnecessary columns
   essential_columns = ['user_id', 'transaction_amount', 'timestamp']
   df_minimal = df[essential_columns]
   ```

3. **K-anonymity:**
   ```python
   # Generalize quasi-identifiers
   df['age_group'] = pd.cut(df['age'], bins=[0, 25, 40, 60, 100])
   df['zip_prefix'] = df['zip_code'].str[:3]
   ```

#### Issue 4: Safety Incidents

**Symptom:** Toxic content detected in model outputs

**Diagnosis:**

```bash
mahavishnu ethics safety monitor \
    --model ./models/chatbot.pkl \
    --logs ./logs/predictions.jsonl \
    --window 24h
```

**Solutions:**

1. **Add output filtering:**
   ```python
   from detoxify import Detoxify

   def safe_generate(prompt, model):
       response = model.generate(prompt)
       toxicity = Detoxify('original').predict(response)

       if max(toxicity.values()) > 0.5:
           return "I cannot provide this response."
       return response
   ```

2. **Fine-tune on safety data:**
   ```python
   # Fine-tune to avoid toxic outputs
   safety_data = load_safety_dataset()
   model.fine_tune(safety_data)
   ```

3. **Human-in-the-loop:**
   ```python
   # Flag risky outputs for review
   if prediction['confidence'] < 0.8:
       prediction['status'] = 'REVIEW_REQUIRED'
       send_to_review(prediction)
   ```

#### Issue 5: Compliance Failure

**Symptom:** Compliance score < 0.8 for required framework

**Diagnosis:**

```bash
mahavishnu ethics compliance check \
    --model ./models/model.pkl \
    --framework gdpr \
    --framework eu_ai_act \
    --detailed \
    --output ./compliance_gap.json
```

**Solutions:**

1. **Address critical gaps:**
   ```python
   # Review compliance gaps
   with open('compliance_gap.json') as f:
       report = json.load(f)

   for gap in report['frameworks']['gdpr']['critical_gaps']:
       print(f"Fix: {gap}")
       create_task(gap, priority='critical')
   ```

2. **Add missing documentation:**
   ```python
   # Create model card
   model_card = generate_model_card(model)
   save_documentation('model_card.md', model_card)

   # Create data sheet
   data_sheet = generate_data_sheet(dataset)
   save_documentation('data_sheet.md', data_sheet)
   ```

3. **Implement consent management:**
   ```bash
   mahavishnu ethics privacy consent \
       --action record \
       --user user123 \
       --purpose "model_training"
   ```

### Getting Help

**Resources:**

1. **Mahavishnu Documentation:**
   - CLI reference: `mahavishnu ethics --help`
   - Integration guide: `/Users/les/Projects/mahavishnu/docs/AI_GOVERNANCE_GUIDE.md`

2. **External Resources:**
   - Google AI Principles: https://ai.google/principles/
   - Microsoft Responsible AI: https://www.microsoft.com/ai/responsible-ai
   - IBM AI Ethics: https://www.ibm.com/watson/ai-ethics/
   - Fairlearn Documentation: https://fairlearn.org/
   - SHAP Documentation: https://shap.readthedocs.io/

3. **Community:**
   - Stack Overflow: Tag questions with `mahavishnu-ai-governance`
   - GitHub Issues: Report bugs and request features

4. **Professional Support:**
   - AI ethics consultants
   - Legal counsel for regulatory compliance
   - Data protection officers (DPO)

---

## Appendix

### Quick Reference Commands

```bash
# Bias Detection
mahavishnu ethics bias detect \
    --model ./model.pkl \
    --dataset ./data.csv \
    --attribute gender \
    --threshold 0.8

# Bias Mitigation
mahavishnu ethics bias mitigate \
    --model ./model.pkl \
    --dataset ./data.csv \
    --technique adversarial \
    --target 0.90

# Explain Decision
mahavishnu ethics explain decision \
    --model ./model.pkl \
    --input '{"feature1": 100}' \
    --method shap \
    --top 10

# Privacy Assessment
mahavishnu ethics privacy assess \
    --dataset ./data.csv \
    --pii name \
    --pii email \
    --technique differential_privacy

# Safety Evaluation
mahavishnu ethics safety evaluate \
    --model ./model.pkl \
    --suite comprehensive \
    --samples 1000

# Compliance Check
mahavishnu ethics compliance check \
    --model ./model.pkl \
    --framework gdpr \
    --framework eu_ai_act

# Deployment Approval
mahavishnu ethics compliance approve \
    --model ./model.pkl \
    --requester "ai-team@company.com" \
    --env production

# Full Audit
mahavishnu ethics compliance audit \
    --model ./model.pkl \
    --type full \
    --output ./audit.json
```

### Glossary

**Algorithmic Bias:** Bias introduced during model design or training algorithm selection.

**Calibration:** Degree to which predicted probabilities reflect true likelihoods.

**Counterfactual Explanation:** Explanation showing what input changes would flip the model's decision.

**Differential Privacy:** Privacy guarantee that individual records cannot be distinguished in aggregated data.

**Disparate Impact:** Ratio of positive outcomes between groups (legal threshold: > 0.8).

**Demographic Parity:** Equal prediction rates across demographic groups.

**Equal Opportunity:** Equal true positive rates across demographic groups.

**Explainability:** Degree to which model decisions can be understood by humans.

**Fairness:** Freedom from bias or favoritism in AI decisions.

**GDPR:** General Data Protection Regulation (EU data protection law).

**Human-in-the-Loop:** Human review or intervention in AI decision-making.

**K-Anonymity:** Privacy model where each record is indistinguishable from k-1 others.

**Label Bias:** Bias introduced in ground truth labels by human annotators.

**Measurement Bias:** Bias in how features or variables are measured or collected.

**Protected Attributes:** Characteristics protected by law (race, gender, age, religion, disability).

**Pseudonymization:** Replacing identifiers with false names or pseudonyms.

**Right to Explanation:** GDPR right to explanation for automated decisions.

**SHAP:** SHapley Additive exPlanations (game theory-based explanation method).

**Transparency:** Degree to which AI systems are open and understandable.

### Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-02-05 | Initial release - Comprehensive AI governance guide |

---

**Document Version:** 1.0
**Last Updated:** 2025-02-05
**Maintained By:** Mahavishnu AI Governance Team

For questions or feedback, please contact: ai-governance@mahavishnu.ai
