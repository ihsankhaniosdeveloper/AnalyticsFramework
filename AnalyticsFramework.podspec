Pod::Spec.new do |spec|
  spec.name         = "AnalyticsFramework"
<<<<<<< HEAD
  spec.version      = "1.0.1"
=======
  spec.version      = "1.0.0"
>>>>>>> 4d0482d31a897737931ae2b9cc1366b1f11c1a3a
  spec.summary      = "A simple analytics framework."

  spec.description  = <<-DESC
    A longer description of the analytics framework that explains what it does and why it is useful.
    This framework provides easy-to-use methods for logging events and tracking analytics in your iOS applications.
  DESC

  spec.homepage     = "https://github.com/ihsankhaniosdeveloper/AnalyticsFramework"
  spec.license      = { :type => "MIT", :file => "LICENSE" }
  spec.author       = { "ihsankhaniosdeveloper" => "ihsankhaniosdeveloper@gmail.com" }

  spec.ios.deployment_target = "12.0"

<<<<<<< HEAD
  spec.source       = { :git => "https://github.com/ihsankhaniosdeveloper/AnalyticsFramework.git", :tag => "1.0.0" }
=======
  spec.source       = { :git => "https://github.com/ihsankhaniosdeveloper/AnalyticsFramework.git", :tag => "#{spec.version}" }
>>>>>>> 4d0482d31a897737931ae2b9cc1366b1f11c1a3a

  spec.source_files  = "AnalyticsFramework/**/*.{swift,h,m}"
  spec.exclude_files = "AnalyticsFramework/Exclude"

  spec.requires_arc = true

  # Dependencies (if any)
  # spec.dependency 'SomeDependency', '~> 1.2.3'
end
