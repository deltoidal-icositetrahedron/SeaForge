pub mod config;
pub mod hull;
pub mod materials;
pub mod propulsion;
pub mod state;

pub use config::{VesselConfig, ZoneSpec};
pub use hull::{HullGeometry, HullZone};
pub use materials::{
    MaterialConfig, MaterialGrade, MaterialModel, MaterialSpec, SealQuality, WeldQuality,
};
pub use propulsion::PropulsionSpec;
pub use state::{VesselState, ZoneState};
