# Rebuilds the shipped sample model files: python -m app.core.ml_samples.build_samples
from app.core.ml_samples import build_iris, sample_file

if __name__ == "__main__":
    print(f"wrote {build_iris(sample_file('iris'))}")
