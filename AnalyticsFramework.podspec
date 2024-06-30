Pod::Spec.new do |spec|
  spec.name         = "AnalyticsFramework"
  spec.version      = "1.0.2"
  spec.summary      = "A simple analytics framework."

  spec.description  = <<-DESC
    A longer description of the analytics framework that explains what it does and why it is useful.
    This framework provides easy-to-use methods for logging events and tracking analytics in your iOS applications.
  DESC

  spec.homepage     = "https://github.com/yourusername/AnalyticsFramework"
  spec.license      = { :type => "MIT", :file => "LICENSE" }
  spec.author       = { "Your Name" => "your-email@example.com" }

  spec.ios.deployment_target = "12.0"

  spec.source       = { :git => "https://github.com/yourusername/AnalyticsFramework.git", :tag => "#{spec.version}" }

  spec.source_files  = "Sources/AnalyticsFramework/**/*.{swift,h,m}"
  spec.exclude_files = "Sources/AnalyticsFramework/Exclude"

  spec.requires_arc = true

  spec.swift_versions = ["5.0", "5.1", "5.2", "5.3", "5.4", "5.5", "5.6"]

  # Dependencies (if any)
  # spec.dependency 'SomeDependency', '~> 1.2.3'
end
