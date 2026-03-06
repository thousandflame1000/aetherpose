// 1. Declare the sub-modules
pub mod bone;
pub mod joint;
pub mod model;
pub mod pose;
pub mod proportions;

// 2. Re-export the primary types for convenient access
pub use bone::BoneId;
pub use model::SkeletonModel;
