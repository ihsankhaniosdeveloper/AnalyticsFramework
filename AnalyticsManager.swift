//
//  AnalyticsManager.swift
//  AnalyticsFramework
//
//  Created by Ahmed Durrani on 30/06/2024.
//

import Foundation
public class AnalyticsManager {
    public static let shared = AnalyticsManager()
    private init() {}
}

public protocol AnalyticsService {
    func logEvent(name: String, parameters: [String: Any])
}
