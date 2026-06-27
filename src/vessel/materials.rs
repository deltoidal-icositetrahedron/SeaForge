use serde::{Deserialize, Serialize};

/// Hull construction material grade.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum MaterialGrade {
    MildSteelA,
    MildSteelE,
    Ah36,
    Dh36,
    Eh36,
    Aluminum5083,
    GrpEGlass,
    CfrpEpoxy,
}

impl MaterialGrade {
    pub fn all() -> &'static [MaterialGrade] {
        &[
            MaterialGrade::MildSteelA,
            MaterialGrade::MildSteelE,
            MaterialGrade::Ah36,
            MaterialGrade::Dh36,
            MaterialGrade::Eh36,
            MaterialGrade::Aluminum5083,
            MaterialGrade::GrpEGlass,
            MaterialGrade::CfrpEpoxy,
        ]
    }

    pub fn spec(self) -> MaterialSpec {
        match self {
            MaterialGrade::MildSteelA => MaterialSpec {
                label: "Mild Steel A",
                density_kg_m3: 7850.0,
                yield_mpa: 235.0,
                uts_mpa: 400.0,
                e_gpa: 206.0,
                k_ic_mpa_sqrtm: 80.0,
                min_temp_c: 0.0,
                sn_slope: 3.0,
                sn_ref_stress_mpa: 71.0,
                sn_ref_cycles: 2_000_000,
                cost_per_kg_usd: 0.85,
                base_corrosion_rate_mm_yr: 0.18,
            },
            MaterialGrade::MildSteelE => MaterialSpec {
                label: "Mild Steel E (cold-grade)",
                density_kg_m3: 7850.0,
                yield_mpa: 235.0,
                uts_mpa: 400.0,
                e_gpa: 206.0,
                k_ic_mpa_sqrtm: 95.0,
                min_temp_c: -40.0,
                sn_slope: 3.0,
                sn_ref_stress_mpa: 71.0,
                sn_ref_cycles: 2_000_000,
                cost_per_kg_usd: 1.10,
                base_corrosion_rate_mm_yr: 0.17,
            },
            MaterialGrade::Ah36 => MaterialSpec {
                label: "AH36 High-Strength Steel",
                density_kg_m3: 7850.0,
                yield_mpa: 355.0,
                uts_mpa: 490.0,
                e_gpa: 206.0,
                k_ic_mpa_sqrtm: 105.0,
                min_temp_c: 0.0,
                sn_slope: 3.0,
                sn_ref_stress_mpa: 80.0,
                sn_ref_cycles: 2_000_000,
                cost_per_kg_usd: 1.25,
                base_corrosion_rate_mm_yr: 0.14,
            },
            MaterialGrade::Dh36 => MaterialSpec {
                label: "DH36 High-Strength Steel",
                density_kg_m3: 7850.0,
                yield_mpa: 355.0,
                uts_mpa: 490.0,
                e_gpa: 206.0,
                k_ic_mpa_sqrtm: 115.0,
                min_temp_c: -20.0,
                sn_slope: 3.0,
                sn_ref_stress_mpa: 80.0,
                sn_ref_cycles: 2_000_000,
                cost_per_kg_usd: 1.40,
                base_corrosion_rate_mm_yr: 0.13,
            },
            MaterialGrade::Eh36 => MaterialSpec {
                label: "EH36 High-Strength Steel",
                density_kg_m3: 7850.0,
                yield_mpa: 355.0,
                uts_mpa: 490.0,
                e_gpa: 206.0,
                k_ic_mpa_sqrtm: 130.0,
                min_temp_c: -40.0,
                sn_slope: 3.0,
                sn_ref_stress_mpa: 80.0,
                sn_ref_cycles: 2_000_000,
                cost_per_kg_usd: 1.60,
                base_corrosion_rate_mm_yr: 0.12,
            },
            MaterialGrade::Aluminum5083 => MaterialSpec {
                label: "Aluminium 5083-H116",
                density_kg_m3: 2660.0,
                yield_mpa: 215.0,
                uts_mpa: 305.0,
                e_gpa: 70.3,
                k_ic_mpa_sqrtm: 35.0,
                min_temp_c: -65.0,
                sn_slope: 5.0,
                sn_ref_stress_mpa: 40.0,
                sn_ref_cycles: 2_000_000,
                cost_per_kg_usd: 4.20,
                base_corrosion_rate_mm_yr: 0.015,
            },
            MaterialGrade::GrpEGlass => MaterialSpec {
                label: "E-glass / Polyester GRP",
                density_kg_m3: 1680.0,
                yield_mpa: 90.0,
                uts_mpa: 220.0,
                e_gpa: 14.0,
                k_ic_mpa_sqrtm: 8.0,
                min_temp_c: -30.0,
                sn_slope: 10.0,
                sn_ref_stress_mpa: 35.0,
                sn_ref_cycles: 2_000_000,
                cost_per_kg_usd: 6.50,
                base_corrosion_rate_mm_yr: 0.002,
            },
            MaterialGrade::CfrpEpoxy => MaterialSpec {
                label: "CFRP Epoxy Laminate",
                density_kg_m3: 1550.0,
                yield_mpa: 300.0,
                uts_mpa: 600.0,
                e_gpa: 70.0,
                k_ic_mpa_sqrtm: 30.0,
                min_temp_c: -55.0,
                sn_slope: 12.0,
                sn_ref_stress_mpa: 150.0,
                sn_ref_cycles: 2_000_000,
                cost_per_kg_usd: 85.0,
                base_corrosion_rate_mm_yr: 0.0,
            },
        }
    }

    /// True if this material corrodes meaningfully in seawater.
    pub fn corrodes(self) -> bool {
        matches!(
            self,
            MaterialGrade::MildSteelA
                | MaterialGrade::MildSteelE
                | MaterialGrade::Ah36
                | MaterialGrade::Dh36
                | MaterialGrade::Eh36
        )
    }
}

/// Physical properties and cost for a hull material.
#[derive(Debug, Clone, Copy)]
pub struct MaterialSpec {
    pub label: &'static str,
    /// [kg/m³]
    pub density_kg_m3: f64,
    /// 0.2% proof strength [MPa]
    pub yield_mpa: f64,
    /// Ultimate tensile strength [MPa]
    pub uts_mpa: f64,
    /// Young's modulus [GPa]
    pub e_gpa: f64,
    /// Plane-strain fracture toughness [MPa·√m]
    pub k_ic_mpa_sqrtm: f64,
    /// Minimum rated service temperature [°C]
    pub min_temp_c: f64,
    /// S-N curve slope exponent m (log-log)
    pub sn_slope: f64,
    /// Class reference fatigue stress at sn_ref_cycles [MPa]
    pub sn_ref_stress_mpa: f64,
    /// Reference cycle count for sn_ref_stress
    pub sn_ref_cycles: u64,
    /// Procurement cost per kilogram [USD]
    pub cost_per_kg_usd: f64,
    /// Baseline seawater corrosion rate at 10°C, 35 ppt, pH 8.1 [mm/year]
    pub base_corrosion_rate_mm_yr: f64,
}

/// Weld joint quality class per IIW/DNV fatigue classification.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum WeldQuality {
    /// Full NDT, post-weld heat treatment, 100% UT — Class B+
    Premium,
    /// UT + visual inspection, standard commercial marine — Class C
    Standard,
    /// Visual inspection only, reduced fatigue allowance — Class D
    Economy,
}

impl WeldQuality {
    pub fn all() -> &'static [WeldQuality] {
        &[WeldQuality::Premium, WeldQuality::Standard, WeldQuality::Economy]
    }

    /// Stress concentration factor at weld toe.
    /// Amplifies nominal stress before applying S-N curve.
    pub fn scf(self) -> f64 {
        match self {
            WeldQuality::Premium  => 1.50,
            WeldQuality::Standard => 2.00,
            WeldQuality::Economy  => 2.65,
        }
    }

    /// Initial defect half-length [m] introduced by the weld process.
    pub fn initial_crack_m(self) -> f64 {
        match self {
            WeldQuality::Premium  => 0.05e-3,
            WeldQuality::Standard => 0.20e-3,
            WeldQuality::Economy  => 0.50e-3,
        }
    }

    /// Cost multiplier relative to Economy.
    pub fn cost_factor(self) -> f64 {
        match self {
            WeldQuality::Premium  => 3.0,
            WeldQuality::Standard => 1.6,
            WeldQuality::Economy  => 1.0,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            WeldQuality::Premium  => "Premium (Class B+)",
            WeldQuality::Standard => "Standard (Class C)",
            WeldQuality::Economy  => "Economy (Class D)",
        }
    }
}

/// Watertight seal specification.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum SealQuality {
    /// Marine-grade EPDM, UV-stabilised, pressure-tested
    Marine,
    /// Commercial EPDM, standard compression
    Commercial,
    /// General-purpose neoprene, minimum specification
    Economy,
}

impl SealQuality {
    pub fn all() -> &'static [SealQuality] {
        &[SealQuality::Marine, SealQuality::Commercial, SealQuality::Economy]
    }

    /// Probability of maintaining integrity per hour of operation in open ocean.
    pub fn hourly_survival_prob(self) -> f64 {
        match self {
            SealQuality::Marine     => 0.99990,
            SealQuality::Commercial => 0.99960,
            SealQuality::Economy    => 0.99850,
        }
    }

    pub fn cost_factor(self) -> f64 {
        match self {
            SealQuality::Marine     => 2.5,
            SealQuality::Commercial => 1.4,
            SealQuality::Economy    => 1.0,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            SealQuality::Marine     => "Marine-grade EPDM",
            SealQuality::Commercial => "Commercial EPDM",
            SealQuality::Economy    => "Economy neoprene",
        }
    }
}
