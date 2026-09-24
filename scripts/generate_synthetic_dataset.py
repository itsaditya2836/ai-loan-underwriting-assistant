"""Synthetic Applicant Dataset Generator for AI Loan Underwriting Assistant.

Generates 100 realistic, logically consistent, reproducible synthetic applicant profiles
for personal and home loan underwriting prototype testing.

Seed 42 ensures reproducible synthetic applicant values and document contents.
PDF metadata/timestamps do not need to be byte-identical.
"""

import json
import os
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import pandas as pd

# Constants for synthetic generation
RANDOM_SEED = 42
TOTAL_APPLICANTS = 100
PROTOTYPE_ANNUAL_INTEREST_RATE = 0.105  # 10.5% per annum for prototype calculations

FIRST_NAMES = [
    "Aarav",
    "Priya",
    "Rohan",
    "Sneha",
    "Aditya",
    "Ananya",
    "Vikram",
    "Neha",
    "Arjun",
    "Pooja",
    "Rahul",
    "Riya",
    "Siddharth",
    "Kavya",
    "Rajesh",
    "Meera",
    "Amit",
    "Divya",
    "Suresh",
    "Sunita",
    "Deepak",
    "Swati",
    "Manoj",
    "Nisha",
    "Karthik",
    "Lavanya",
    "Harish",
    "Shilpa",
    "Sanjay",
    "Rashmi",
    "Varun",
    "Shreya",
    "Nikhil",
    "Tanvi",
    "Pradeep",
    "Aishwarya",
    "Manish",
    "Preeti",
    "Sandeep",
    "Shruti",
    "Vijay",
    "Geeta",
    "Ajay",
    "Vandana",
    "Chetan",
    "Rekha",
    "Gaurav",
    "Pallavi",
    "Rakesh",
    "Anita",
    "Abhishek",
    "Kiran",
    "Naveen",
    "Archana",
    "Ganesh",
    "Smita",
    "Mohit",
    "Bhavna",
    "Kunal",
    "Aparna",
    "Alok",
    "Madhavi",
    "Hemant",
    "Rupali",
    "Yash",
    "Monika",
    "Sachin",
    "Usha",
    "Prashant",
    "Komal",
    "Mayank",
    "Sarita",
    "Vivek",
    "Anjali",
    "Dinesh",
    "Sangeeta",
    "Anand",
    "Seema",
    "Vinay",
    "Pushpa",
    "Ashish",
    "Deepa",
    "Tarun",
    "Jyoti",
    "Pankaj",
    "Renu",
    "Tushar",
    "Suman",
    "Sunil",
    "Radha",
    "Rajiv",
    "Gayatri",
    "Mahesh",
    "Kalpana",
    "Satish",
    "Neetu",
    "Mukesh",
    "Lata",
    "Ramesh",
    "Vidya",
    "Jayesh",
    "Sudha",
    "Bhupesh",
    "Alka",
]

LAST_NAMES = [
    "Sharma",
    "Patel",
    "Verma",
    "Iyer",
    "Rao",
    "Gupta",
    "Reddy",
    "Nair",
    "Singh",
    "Joshi",
    "Mehta",
    "Kumar",
    "Kulkarni",
    "Bhat",
    "Nambiar",
    "Deshmukh",
    "Pillai",
    "Choudhury",
    "Das",
    "Sen",
    "Chatterjee",
    "Menon",
    "Agarwal",
    "Saxena",
    "Tripathi",
    "Tiwari",
    "Mishra",
    "Hegde",
    "Bhattacharya",
    "Chauhan",
    "Pandey",
    "Ghosh",
    "Sinha",
    "Prasad",
    "Naidu",
    "Shetty",
    "Venkatesh",
    "Kapoor",
    "Malhotra",
    "Khanna",
    "Soni",
    "Chawla",
    "Bansal",
    "Goel",
    "Bhardwaj",
    "Rawat",
    "Goswami",
    "Dubey",
]

CITIES = [
    "Bengaluru",
    "Chennai",
    "Hyderabad",
    "Mumbai",
    "Pune",
    "Delhi",
    "Kolkata",
    "Coimbatore",
    "Mysuru",
    "Kochi",
    "Ahmedabad",
    "Jaipur",
]

SALARIED_EMPLOYERS = [
    "TechNova Solutions Pvt Ltd",
    "BluePeak Systems Pvt Ltd",
    "Vertex Digital Services",
    "GreenField Consulting",
    "Apex Manufacturing Ltd",
    "Zenith Logistics Ltd",
    "Horizon Enterprises",
    "CloudPulse Technologies",
    "Indus Global Analytics",
    "Trident Engineering Corp",
    "Nexus Software India",
    "Pinnacle Infotech Solutions",
]

SELF_EMPLOYED_BUSINESSES = [
    "Apex Retail Ventures",
    "Surya Consulting Services",
    "Zenith Trading Corp",
    "Om Enterprises",
    "Spark Design Studio",
    "Vanguard Logistics Services",
    "BrightPath Educational Services",
    "UrbanCraft Interiors",
    "Matrix Healthcare Solutions",
]


def calculate_emi(principal: float, annual_rate: float, tenure_months: int) -> float:
    """Calculate monthly loan EMI using the standard amortizing loan formula.

    Formula: EMI = P * r * (1+r)^n / ((1+r)^n - 1)

    Args:
        principal: Principal loan amount.
        annual_rate: Annual nominal interest rate (e.g. 0.105 for 10.5%).
        tenure_months: Number of monthly installment periods.

    Returns:
        Rounded monthly EMI amount.
    """
    if tenure_months <= 0 or principal <= 0:
        return 0.0
    r = annual_rate / 12.0
    if r == 0:
        return round(principal / tenure_months, 2)
    emi = principal * r * ((1 + r) ** tenure_months) / (((1 + r) ** tenure_months) - 1)
    return round(emi, 2)


def generate_unique_names(count: int, rng: random.Random) -> List[str]:
    """Generate a list of distinct synthetic Indian names."""
    pairs = set()
    names = []
    # Exhaustive pairing candidates
    candidates = [f"{fn} {ln}" for fn in FIRST_NAMES for ln in LAST_NAMES]
    rng.shuffle(candidates)

    for name in candidates:
        if name not in pairs:
            pairs.add(name)
            names.append(name)
        if len(names) == count:
            break

    if len(names) < count:
        raise ValueError(f"Could not generate {count} unique names from pool.")
    return names


def generate_applicant_profile(
    applicant_id: str,
    name: str,
    target_category: str,
    rng: random.Random,
) -> Dict[str, Any]:
    """Generate a single coherent synthetic applicant matching a target risk profile."""
    gender = rng.choice(["Male", "Female"])
    city = rng.choice(CITIES)
    emp_type = "SALARIED" if rng.random() < 0.82 else "SELF_EMPLOYED"

    if emp_type == "SALARIED":
        employer = rng.choice(SALARIED_EMPLOYERS)
    else:
        employer = rng.choice(SELF_EMPLOYED_BUSINESSES)

    # Category-informed feature distributions with realistic internal variation
    if target_category == "LOW_RISK":
        age = rng.randint(28, 55)
        emp_years = round(rng.uniform(4.0, 20.0), 1)
        monthly_income = float(rng.choice(range(70000, 220000, 5000)))
        credit_score = rng.randint(750, 830)
        # Low obligations
        existing_emi = float(rng.choice(range(0, int(monthly_income * 0.15), 2000)))
        loan_amount = float(rng.choice(range(500000, 3500000, 50000)))
        loan_tenure = rng.choice([36, 48, 60, 84, 120, 180])
        bank_balance = float(rng.choice(range(150000, 1200000, 25000)))
        monthly_expenses = float(
            rng.choice(range(20000, int(monthly_income * 0.35), 2000))
        )
        dependents = rng.randint(0, 2)

    elif target_category == "MEDIUM_RISK":
        age = rng.randint(24, 58)
        emp_years = round(rng.uniform(2.5, 15.0), 1)
        monthly_income = float(rng.choice(range(45000, 160000, 5000)))
        credit_score = rng.randint(680, 749)
        existing_emi = float(rng.choice(range(5000, int(monthly_income * 0.28), 2000)))
        loan_amount = float(rng.choice(range(400000, 3000000, 50000)))
        loan_tenure = rng.choice([24, 36, 48, 60, 84, 120])
        bank_balance = float(rng.choice(range(40000, 500000, 15000)))
        monthly_expenses = float(
            rng.choice(range(18000, int(monthly_income * 0.45), 2000))
        )
        dependents = rng.randint(1, 3)

    elif target_category == "HIGH_RISK":
        age = rng.randint(22, 50)
        emp_years = round(rng.uniform(0.8, 6.0), 1)
        monthly_income = float(rng.choice(range(25000, 90000, 2500)))
        credit_score = rng.randint(520, 649)
        # Heavy obligations
        existing_emi = float(rng.choice(range(8000, int(monthly_income * 0.45), 2000)))
        loan_amount = float(rng.choice(range(300000, 2500000, 50000)))
        loan_tenure = rng.choice([12, 24, 36, 48, 60])
        bank_balance = float(rng.choice(range(10000, 150000, 5000)))
        monthly_expenses = float(
            rng.choice(range(12000, int(monthly_income * 0.50), 1500))
        )
        dependents = rng.randint(1, 4)

    else:  # BORDERLINE
        age = rng.randint(26, 52)
        emp_years = round(rng.uniform(2.0, 8.0), 1)
        monthly_income = float(rng.choice(range(50000, 120000, 2500)))
        # Credit score right on policy boundary (640-675)
        credit_score = rng.randint(640, 675)
        # Existing EMI tuned so total DTI is around 45% - 55%
        existing_emi = float(rng.choice(range(10000, int(monthly_income * 0.32), 2000)))
        loan_amount = float(rng.choice(range(600000, 2800000, 50000)))
        loan_tenure = rng.choice([36, 48, 60, 84])
        bank_balance = float(rng.choice(range(35000, 250000, 10000)))
        monthly_expenses = float(
            rng.choice(range(18000, int(monthly_income * 0.40), 2000))
        )
        dependents = rng.randint(1, 3)

    # Derived calculations
    estimated_new_emi = calculate_emi(
        loan_amount, PROTOTYPE_ANNUAL_INTEREST_RATE, loan_tenure
    )
    total_monthly_obligations = round(existing_emi + monthly_expenses, 2)
    dti_ratio = round(((existing_emi + estimated_new_emi) / monthly_income) * 100.0, 2)
    loan_to_income_ratio = round(loan_amount / (monthly_income * 12.0), 2)

    return {
        "applicant_id": applicant_id,
        "name": name,
        "age": age,
        "gender": gender,
        "employment_type": emp_type,
        "employer_name": employer,
        "employment_years": emp_years,
        "monthly_income": monthly_income,
        "existing_emi": existing_emi,
        "loan_amount": loan_amount,
        "loan_tenure": loan_tenure,
        "credit_score": credit_score,
        "bank_balance": bank_balance,
        "city": city,
        "monthly_expenses": monthly_expenses,
        "number_of_dependents": dependents,
        "total_monthly_obligations": total_monthly_obligations,
        "estimated_new_emi": estimated_new_emi,
        "dti_ratio": dti_ratio,
        "loan_to_income_ratio": loan_to_income_ratio,
        "profile_category": target_category,
    }


def generate_dataset() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Generate 100 synthetic applicants with target category distribution.

    APP0026..APP0030 are calibrated strictly to the BORDERLINE profile:
    - Credit score: approximately 640-675
    - DTI ratio: approximately 48%-55%
    - Mathematical consistency: DTI = (existing_emi + estimated_new_emi) / monthly_income
    """
    rng = random.Random(RANDOM_SEED)
    names = generate_unique_names(TOTAL_APPLICANTS, rng)

    # Initial distribution categories
    categories = (
        ["LOW_RISK"] * 30
        + ["MEDIUM_RISK"] * 30
        + ["HIGH_RISK"] * 20
        + ["BORDERLINE"] * 20
    )
    rng.shuffle(categories)

    applicants: List[Dict[str, Any]] = []

    # 1. Generate APP0001..APP0025 with baseline cohort categories
    for idx in range(25):
        app_id = f"APP{idx + 1:04d}"
        profile = generate_applicant_profile(app_id, names[idx], categories[idx], rng)
        applicants.append(profile)

    # 2. Generate APP0026..APP0030 strictly as calibrated BORDERLINE applicants
    r = PROTOTYPE_ANNUAL_INTEREST_RATE / 12.0
    rng_b = random.Random(42 + 26)

    for idx in range(25, 30):
        app_id = f"APP{idx + 1:04d}"
        name = names[idx]
        gender = rng.choice(["Male", "Female"])
        city = rng.choice(CITIES)
        emp_type = "SALARIED" if rng.random() < 0.8 else "SELF_EMPLOYED"
        employer = (
            rng.choice(SALARIED_EMPLOYERS)
            if emp_type == "SALARIED"
            else rng.choice(SELF_EMPLOYED_BUSINESSES)
        )
        age = rng.randint(28, 50)
        emp_years = round(rng.uniform(2.5, 9.0), 1)

        # Calibrated financial attributes for 48%-55% DTI and 640-675 Credit Score
        monthly_income = float(rng_b.choice(range(70000, 125000, 2500)))
        credit_score = rng_b.randint(640, 675)
        target_dti = rng_b.uniform(0.485, 0.540)
        target_total_debt = monthly_income * target_dti
        existing_emi = round((monthly_income * rng_b.uniform(0.14, 0.20)) / 500) * 500.0
        target_new_emi = target_total_debt - existing_emi

        loan_tenure = rng_b.choice([36, 48, 60, 84])
        factor = ((1 + r) ** loan_tenure - 1) / (r * (1 + r) ** loan_tenure)
        raw_loan = target_new_emi * factor
        loan_amount = round(raw_loan / 10000) * 10000.0

        estimated_new_emi = calculate_emi(
            loan_amount, PROTOTYPE_ANNUAL_INTEREST_RATE, loan_tenure
        )
        dti_ratio = round(
            ((existing_emi + estimated_new_emi) / monthly_income) * 100.0, 2
        )
        loan_to_income_ratio = round(loan_amount / (monthly_income * 12.0), 2)
        bank_balance = float(rng_b.choice(range(50000, 250000, 10000)))
        monthly_expenses = float(
            rng_b.choice(range(15000, int(monthly_income * 0.35), 1500))
        )
        dependents = rng_b.randint(1, 3)
        total_monthly_obligations = round(existing_emi + monthly_expenses, 2)

        profile = {
            "applicant_id": app_id,
            "name": name,
            "age": age,
            "gender": gender,
            "employment_type": emp_type,
            "employer_name": employer,
            "employment_years": emp_years,
            "monthly_income": monthly_income,
            "existing_emi": existing_emi,
            "loan_amount": loan_amount,
            "loan_tenure": loan_tenure,
            "credit_score": credit_score,
            "bank_balance": bank_balance,
            "city": city,
            "monthly_expenses": monthly_expenses,
            "number_of_dependents": dependents,
            "total_monthly_obligations": total_monthly_obligations,
            "estimated_new_emi": estimated_new_emi,
            "dti_ratio": dti_ratio,
            "loan_to_income_ratio": loan_to_income_ratio,
            "profile_category": "BORDERLINE",
        }
        applicants.append(profile)

    # 3. Generate APP0031..APP0100 balancing categories to exact 30/30/20/20 totals
    # Current counts in 0..29: LOW=7, MEDIUM=8, HIGH=4, BORDERLINE=11
    # Remaining needed for 70 applicants: LOW=23, MEDIUM=22, HIGH=16, BORDERLINE=9
    rem_categories = (
        ["LOW_RISK"] * 23
        + ["MEDIUM_RISK"] * 22
        + ["HIGH_RISK"] * 16
        + ["BORDERLINE"] * 9
    )
    rng_rem = random.Random(RANDOM_SEED)
    rng_rem.shuffle(rem_categories)

    for idx in range(30, 100):
        app_id = f"APP{idx + 1:04d}"
        cat = rem_categories[idx - 30]
        profile = generate_applicant_profile(app_id, names[idx], cat, rng)
        applicants.append(profile)

    metadata = {
        "dataset_name": "Synthetic Loan Applicant Dataset",
        "version": "1.0.0",
        "generation_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "number_of_applicants": TOTAL_APPLICANTS,
        "number_of_document_packages": 30,
        "prototype_annual_interest_rate": PROTOTYPE_ANNUAL_INTEREST_RATE,
        "profile_distribution": {
            "LOW_RISK": sum(
                1 for a in applicants if a["profile_category"] == "LOW_RISK"
            ),
            "MEDIUM_RISK": sum(
                1 for a in applicants if a["profile_category"] == "MEDIUM_RISK"
            ),
            "HIGH_RISK": sum(
                1 for a in applicants if a["profile_category"] == "HIGH_RISK"
            ),
            "BORDERLINE": sum(
                1 for a in applicants if a["profile_category"] == "BORDERLINE"
            ),
        },
        "purpose": "Experimental input dataset for multi-agent loan underwriting decision-support prototype.",
        "synthetic_data_notice": "ALL DATA IS SYNTHETIC. Contains no real personal, banking, or credit data.",
    }

    return applicants, metadata


def main() -> None:
    """Generate and save applicants.csv, applicants.json, and dataset_metadata.json."""
    output_dir = "data/synthetic_data"
    os.makedirs(output_dir, exist_ok=True)

    applicants, metadata = generate_dataset()

    # Save CSV
    df = pd.DataFrame(applicants)
    csv_path = os.path.join(output_dir, "applicants.csv")
    df.to_csv(csv_path, index=False)
    print(f"Saved {len(df)} applicants to {csv_path}")

    # Save JSON
    json_path = os.path.join(output_dir, "applicants.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(applicants, f, indent=2)
    print(f"Saved {len(applicants)} applicants to {json_path}")

    # Save Metadata
    meta_path = os.path.join(output_dir, "dataset_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved dataset metadata to {meta_path}")


if __name__ == "__main__":
    main()
