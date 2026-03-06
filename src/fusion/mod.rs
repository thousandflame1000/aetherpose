#![allow(clippy::module_inception)]

pub mod assignment;
pub mod confidence;
pub mod fusion;
pub mod weighting;

pub use fusion::{AuthoritativePose, FusionEngine};
