//
//  AnalyticsFramework.swift
//  AnalyticsFramework
//
//  Created by Ahmed Durrani on 30/06/2024.
//

import Foundation
public class AnalyticsFramework: AnalyticsService{
    public init() {}
    
    public func logEvent(name: String, parameters: [String: Any]) {
        print("Event logged: \(name) with parameters: \(parameters)")
    }
}
