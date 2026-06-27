use serde::{Deserialize, Serialize};

use crate::environment::ocean::OceanConditions;

/// Geographic coordinate (WGS-84).
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct GeoPoint {
    pub lat_deg: f64,
    pub lon_deg: f64,
}

impl GeoPoint {
    pub fn new(lat_deg: f64, lon_deg: f64) -> Self {
        Self { lat_deg, lon_deg }
    }
}

/// One leg of the voyage with its own sea state and water conditions.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RouteSegment {
    pub from: GeoPoint,
    pub to: GeoPoint,
    /// Great-circle distance [nautical miles]
    pub distance_nm: f64,
    /// Vessel heading for this leg [degrees true]
    pub heading_deg: f64,
    /// Ocean conditions representative of this leg
    pub conditions: OceanConditions,
    /// Label for reporting
    pub label: String,
}

/// Complete voyage definition from origin to destination.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VoyageRoute {
    pub origin: GeoPoint,
    pub destination: GeoPoint,
    pub segments: Vec<RouteSegment>,
}

impl VoyageRoute {
    pub fn total_distance_nm(&self) -> f64 {
        self.segments.iter().map(|s| s.distance_nm).sum()
    }
}
