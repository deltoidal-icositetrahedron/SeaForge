use serde::{de, Deserialize, Deserializer, Serialize};

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
                label: "Mild Steel A".into(),
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
                label: "Mild Steel E (cold-grade)".into(),
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
                label: "AH36 High-Strength Steel".into(),
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
                label: "DH36 High-Strength Steel".into(),
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
                label: "EH36 High-Strength Steel".into(),
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
                label: "Aluminium 5083-H116".into(),
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
                label: "E-glass / Polyester GRP".into(),
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
                label: "CFRP Epoxy Laminate".into(),
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

    pub fn from_key(key: &str) -> Option<Self> {
        let normalized = normalize_material_key(key);
        Some(match normalized.as_str() {
            "mildsteela" | "mildsteeltemperate" | "mildsteel" => MaterialGrade::MildSteelA,
            "mildsteele" | "mildsteelcoldweather" | "mildsteelcoldgrade" => {
                MaterialGrade::MildSteelE
            }
            "ah36" | "ah36steel" | "highstrengthah36" => MaterialGrade::Ah36,
            "dh36" | "dh36steel" | "highstrengthdh36" => MaterialGrade::Dh36,
            "eh36" | "eh36steel" | "highstrengtheh36" | "eh40" | "eh40steel" => MaterialGrade::Eh36,
            "aluminum5083" | "aluminium5083" | "al5083" => MaterialGrade::Aluminum5083,
            "grp" | "grpeglass" | "grpfiberglass" | "fiberglass" => MaterialGrade::GrpEGlass,
            "cfrp" | "cfrpepoxy" | "cfrpcarbonfiber" | "carbonfiber" => MaterialGrade::CfrpEpoxy,
            _ => return None,
        })
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(untagged)]
pub enum MaterialModel {
    Grade(MaterialGrade),
    Config(MaterialConfig),
}

impl<'de> Deserialize<'de> for MaterialModel {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = serde_json::Value::deserialize(deserializer)?;
        if let Some(key) = value.as_str() {
            return MaterialGrade::from_key(key)
                .map(MaterialModel::Grade)
                .ok_or_else(|| de::Error::custom(format!("unknown material grade '{key}'")));
        }

        let config = MaterialConfig::deserialize(value).map_err(de::Error::custom)?;
        Ok(MaterialModel::Config(config))
    }
}

impl MaterialModel {
    pub fn spec(&self) -> MaterialSpec {
        match self {
            MaterialModel::Grade(grade) => grade.spec(),
            MaterialModel::Config(config) => config.spec(),
        }
    }

    pub fn corrodes(&self) -> bool {
        self.spec().base_corrosion_rate_mm_yr > 0.0
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct MaterialConfig {
    #[serde(default)]
    pub grade: Option<String>,
    #[serde(default)]
    pub label: Option<String>,
    #[serde(default)]
    pub strength_index: Option<f64>,
    #[serde(default)]
    pub cost: Option<f64>,
    #[serde(default)]
    pub cost_unit: Option<String>,
    #[serde(default)]
    pub heat_threshold_c: Option<f64>,
    #[serde(default)]
    pub cold_threshold_c: Option<f64>,
    #[serde(default)]
    pub dust_coeff: Option<f64>,
    #[serde(default)]
    pub humidity_coeff: Option<f64>,
    #[serde(default)]
    pub salinity_coeff: Option<f64>,
    #[serde(default)]
    pub uv_coeff: Option<f64>,

    #[serde(default)]
    pub density_kg_m3: Option<f64>,
    #[serde(default)]
    pub yield_mpa: Option<f64>,
    #[serde(default)]
    pub uts_mpa: Option<f64>,
    #[serde(default)]
    pub e_gpa: Option<f64>,
    #[serde(default)]
    pub k_ic_mpa_sqrtm: Option<f64>,
    #[serde(default)]
    pub min_temp_c: Option<f64>,
    #[serde(default)]
    pub sn_slope: Option<f64>,
    #[serde(default)]
    pub sn_ref_stress_mpa: Option<f64>,
    #[serde(default)]
    pub sn_ref_cycles: Option<u64>,
    #[serde(default)]
    pub cost_per_kg_usd: Option<f64>,
    #[serde(default)]
    pub base_corrosion_rate_mm_yr: Option<f64>,
}

impl MaterialConfig {
    pub fn spec(&self) -> MaterialSpec {
        let mut spec = self.base_spec();

        if let Some(label) = &self.label {
            spec.label = label.clone();
        }
        if let Some(value) = self.density_kg_m3 {
            spec.density_kg_m3 = value;
        }
        if let Some(value) = self.yield_mpa {
            spec.yield_mpa = value;
        }
        if let Some(value) = self.uts_mpa {
            spec.uts_mpa = value;
        }
        if let Some(value) = self.e_gpa {
            spec.e_gpa = value;
        }
        if let Some(value) = self.k_ic_mpa_sqrtm {
            spec.k_ic_mpa_sqrtm = value;
        }
        if let Some(value) = self.min_temp_c.or(self.cold_threshold_c) {
            spec.min_temp_c = value;
        }
        if let Some(value) = self.sn_slope {
            spec.sn_slope = value;
        }
        if let Some(value) = self.sn_ref_stress_mpa {
            spec.sn_ref_stress_mpa = value;
        }
        if let Some(value) = self.sn_ref_cycles {
            spec.sn_ref_cycles = value;
        }
        if let Some(value) = self.base_corrosion_rate_mm_yr {
            spec.base_corrosion_rate_mm_yr = value;
        } else if let Some(salinity_coeff) = self.salinity_coeff {
            spec.base_corrosion_rate_mm_yr = (salinity_coeff * 0.95).clamp(0.0, 0.35);
        }

        if let Some(value) = self.cost_per_kg_usd {
            spec.cost_per_kg_usd = value;
        } else if let Some(value) = self.cost_as_usd_per_kg(spec.density_kg_m3) {
            spec.cost_per_kg_usd = value;
        }

        spec
    }

    fn base_spec(&self) -> MaterialSpec {
        if let Some(grade) = &self.grade {
            if let Some(material_grade) = MaterialGrade::from_key(grade) {
                return material_grade.spec();
            }
            if let Some(spec) = landforge_grade_spec(grade) {
                return spec;
            }
        }

        let strength = self.strength_index.unwrap_or(0.52).clamp(0.05, 1.0);
        MaterialSpec {
            label: self
                .label
                .clone()
                .or_else(|| self.grade.clone())
                .unwrap_or_else(|| "Custom Material".into()),
            density_kg_m3: 7850.0,
            yield_mpa: 90.0 + 760.0 * strength,
            uts_mpa: 160.0 + 900.0 * strength,
            e_gpa: 70.0 + 150.0 * strength,
            k_ic_mpa_sqrtm: 20.0 + 115.0 * strength,
            min_temp_c: self.cold_threshold_c.unwrap_or(0.0),
            sn_slope: if strength > 0.75 { 4.0 } else { 3.0 },
            sn_ref_stress_mpa: 35.0 + 115.0 * strength,
            sn_ref_cycles: 2_000_000,
            cost_per_kg_usd: 1.25,
            base_corrosion_rate_mm_yr: self
                .salinity_coeff
                .map(|value| (value * 0.95).clamp(0.0, 0.35))
                .unwrap_or(0.10),
        }
    }

    fn cost_as_usd_per_kg(&self, density_kg_m3: f64) -> Option<f64> {
        let cost = self.cost?;
        let unit = self
            .cost_unit
            .as_deref()
            .unwrap_or("USD/kg")
            .to_ascii_lowercase();

        if unit.contains("/kg") {
            Some(cost)
        } else if unit.contains("/l") || unit.contains("per l") {
            let kg_per_l = density_kg_m3 / 1000.0;
            if kg_per_l > 0.0 {
                Some(cost / kg_per_l)
            } else {
                Some(cost)
            }
        } else {
            Some(cost)
        }
    }
}

/// Physical properties and cost for a hull material.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MaterialSpec {
    pub label: String,
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

fn landforge_grade_spec(key: &str) -> Option<MaterialSpec> {
    let normalized = normalize_material_key(key);
    Some(match normalized.as_str() {
        "al5086" | "aluminum5086" | "aluminium5086" => MaterialSpec {
            label: "Aluminum 5086".into(),
            density_kg_m3: 2660.0,
            yield_mpa: 195.0,
            uts_mpa: 290.0,
            e_gpa: 70.3,
            k_ic_mpa_sqrtm: 35.0,
            min_temp_c: -65.0,
            sn_slope: 5.0,
            sn_ref_stress_mpa: 38.0,
            sn_ref_cycles: 2_000_000,
            cost_per_kg_usd: 4.0,
            base_corrosion_rate_mm_yr: 0.018,
        },
        "tigrade5" | "titaniumgrade5" => MaterialSpec {
            label: "Titanium Grade 5".into(),
            density_kg_m3: 4430.0,
            yield_mpa: 880.0,
            uts_mpa: 950.0,
            e_gpa: 114.0,
            k_ic_mpa_sqrtm: 75.0,
            min_temp_c: -200.0,
            sn_slope: 5.0,
            sn_ref_stress_mpa: 240.0,
            sn_ref_cycles: 2_000_000,
            cost_per_kg_usd: 112.5,
            base_corrosion_rate_mm_yr: 0.001,
        },
        "stainlesssteel" | "stainlesssteel316" => MaterialSpec {
            label: "Stainless Steel 316".into(),
            density_kg_m3: 8000.0,
            yield_mpa: 290.0,
            uts_mpa: 580.0,
            e_gpa: 193.0,
            k_ic_mpa_sqrtm: 120.0,
            min_temp_c: -196.0,
            sn_slope: 3.0,
            sn_ref_stress_mpa: 75.0,
            sn_ref_cycles: 2_000_000,
            cost_per_kg_usd: 5.0,
            base_corrosion_rate_mm_yr: 0.015,
        },
        "stainlesssteel304" => MaterialSpec {
            label: "Stainless Steel 304".into(),
            density_kg_m3: 8000.0,
            yield_mpa: 215.0,
            uts_mpa: 515.0,
            e_gpa: 193.0,
            k_ic_mpa_sqrtm: 120.0,
            min_temp_c: -196.0,
            sn_slope: 3.0,
            sn_ref_stress_mpa: 70.0,
            sn_ref_cycles: 2_000_000,
            cost_per_kg_usd: 4.0,
            base_corrosion_rate_mm_yr: 0.025,
        },
        "nickelalloy" | "nickelalloy625" | "nickelsuperalloy" => MaterialSpec {
            label: "Nickel Alloy 625".into(),
            density_kg_m3: 8440.0,
            yield_mpa: 460.0,
            uts_mpa: 880.0,
            e_gpa: 207.0,
            k_ic_mpa_sqrtm: 150.0,
            min_temp_c: -196.0,
            sn_slope: 3.0,
            sn_ref_stress_mpa: 115.0,
            sn_ref_cycles: 2_000_000,
            cost_per_kg_usd: 42.5,
            base_corrosion_rate_mm_yr: 0.003,
        },
        "chromolysteel" => MaterialSpec {
            label: "Chromoly Steel".into(),
            density_kg_m3: 7850.0,
            yield_mpa: 435.0,
            uts_mpa: 670.0,
            e_gpa: 205.0,
            k_ic_mpa_sqrtm: 80.0,
            min_temp_c: -20.0,
            sn_slope: 3.0,
            sn_ref_stress_mpa: 90.0,
            sn_ref_cycles: 2_000_000,
            cost_per_kg_usd: 3.0,
            base_corrosion_rate_mm_yr: 0.16,
        },
        "castiron" => MaterialSpec {
            label: "Cast Iron".into(),
            density_kg_m3: 7200.0,
            yield_mpa: 130.0,
            uts_mpa: 200.0,
            e_gpa: 110.0,
            k_ic_mpa_sqrtm: 20.0,
            min_temp_c: 0.0,
            sn_slope: 3.0,
            sn_ref_stress_mpa: 35.0,
            sn_ref_cycles: 2_000_000,
            cost_per_kg_usd: 1.25,
            base_corrosion_rate_mm_yr: 0.22,
        },
        "kevlarcomposite" => MaterialSpec {
            label: "Kevlar Composite".into(),
            density_kg_m3: 1440.0,
            yield_mpa: 220.0,
            uts_mpa: 360.0,
            e_gpa: 70.0,
            k_ic_mpa_sqrtm: 25.0,
            min_temp_c: -196.0,
            sn_slope: 10.0,
            sn_ref_stress_mpa: 85.0,
            sn_ref_cycles: 2_000_000,
            cost_per_kg_usd: 45.0,
            base_corrosion_rate_mm_yr: 0.0,
        },
        "ceramiccomposite" | "tungstencarbide" => MaterialSpec {
            label: key.to_string(),
            density_kg_m3: 3900.0,
            yield_mpa: 500.0,
            uts_mpa: 700.0,
            e_gpa: 300.0,
            k_ic_mpa_sqrtm: 8.0,
            min_temp_c: 0.0,
            sn_slope: 8.0,
            sn_ref_stress_mpa: 130.0,
            sn_ref_cycles: 2_000_000,
            cost_per_kg_usd: if normalized == "tungstencarbide" {
                66.5
            } else {
                85.0
            },
            base_corrosion_rate_mm_yr: 0.0,
        },
        _ => return None,
    })
}

fn normalize_material_key(key: &str) -> String {
    key.chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .flat_map(|c| c.to_lowercase())
        .collect()
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
        &[
            WeldQuality::Premium,
            WeldQuality::Standard,
            WeldQuality::Economy,
        ]
    }

    /// Stress concentration factor at weld toe.
    /// Amplifies nominal stress before applying S-N curve.
    pub fn scf(self) -> f64 {
        match self {
            WeldQuality::Premium => 1.50,
            WeldQuality::Standard => 2.00,
            WeldQuality::Economy => 2.65,
        }
    }

    /// Initial defect half-length [m] introduced by the weld process.
    pub fn initial_crack_m(self) -> f64 {
        match self {
            WeldQuality::Premium => 0.05e-3,
            WeldQuality::Standard => 0.20e-3,
            WeldQuality::Economy => 0.50e-3,
        }
    }

    /// Cost multiplier relative to Economy.
    pub fn cost_factor(self) -> f64 {
        match self {
            WeldQuality::Premium => 3.0,
            WeldQuality::Standard => 1.6,
            WeldQuality::Economy => 1.0,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            WeldQuality::Premium => "Premium (Class B+)",
            WeldQuality::Standard => "Standard (Class C)",
            WeldQuality::Economy => "Economy (Class D)",
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
        &[
            SealQuality::Marine,
            SealQuality::Commercial,
            SealQuality::Economy,
        ]
    }

    /// Probability of maintaining integrity per hour of operation in open ocean.
    pub fn hourly_survival_prob(self) -> f64 {
        match self {
            SealQuality::Marine => 0.99990,
            SealQuality::Commercial => 0.99960,
            SealQuality::Economy => 0.99850,
        }
    }

    pub fn cost_factor(self) -> f64 {
        match self {
            SealQuality::Marine => 2.5,
            SealQuality::Commercial => 1.4,
            SealQuality::Economy => 1.0,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            SealQuality::Marine => "Marine-grade EPDM",
            SealQuality::Commercial => "Commercial EPDM",
            SealQuality::Economy => "Economy neoprene",
        }
    }
}
